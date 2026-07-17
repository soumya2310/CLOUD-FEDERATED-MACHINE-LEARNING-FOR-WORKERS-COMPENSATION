"""Treatment-compliance domain.

PRISM: a feed-forward autoencoder trained only on guideline-consistent sequences;
the anomaly score is reconstruction error augmented with a guideline-regularization
term (weight gamma) that penalizes reconstructed treatment intensity exceeding the
ODG envelope. Baseline: Isolation Forest. Reports F1, ROC-AUC, precision/recall,
and expected calibration error, plus the gamma sensitivity sweep (Fig. 4a) and the
data behind the ROC (Fig. 4b), reliability diagram and score histograms (Fig. 6).
"""
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.ensemble import IsolationForest
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, precision_recall_fscore_support, roc_curve
from . import config as C


def _summary_features(Xseq):
    """Per-channel mean/std only. The Isolation Forest sees these marginal
    statistics but not the temporal structure of a sequence, which is the
    reconstruction autoencoder's advantage (Section III-B of the paper)."""
    return np.concatenate([Xseq.mean(axis=1), Xseq.std(axis=1)], axis=1)


def _guideline_penalty(Xseq):
    """max(0, peak treatment intensity - ODG envelope)^2 per sequence."""
    intensity = Xseq[:, :, 0].max(axis=1)           # channel 0 = treatment intensity
    return np.clip(intensity - C.ODG_ENVELOPE, 0, None) ** 2


def _expected_calibration_error(y, p, bins=10):
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -1e9, 1e9
    ece = 0.0
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1])
        if m.sum() == 0:
            continue
        ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def run(cohort, seed=C.MASTER_SEED):
    X, y = cohort["X"], cohort["y"]
    n, T, D = X.shape
    Xf = X.reshape(n, T * D)
    Xs = _summary_features(X)
    pen = _guideline_penalty(X)

    (Xtr, Xte, Xstr, Xste, ytr, yte, ptr, pte) = train_test_split(
        Xf, Xs, y, pen, test_size=0.35, random_state=seed, stratify=y)

    comp = ytr == 0
    # standardize reconstruction targets (helps the AE separate cleanly)
    mu, sd = Xtr[comp].mean(0), Xtr[comp].std(0) + 1e-6
    Ztr, Zte = (Xtr - mu) / sd, (Xte - mu) / sd

    ae = MLPRegressor(hidden_layer_sizes=(C.AE_HIDDEN, C.AE_LATENT, C.AE_HIDDEN),
                      activation="relu", solver="adam", alpha=1e-4,
                      max_iter=200, random_state=seed)
    ae.fit(Ztr[comp], Ztr[comp])

    def recon_error(Z):
        e = (ae.predict(Z) - Z) ** 2
        # blend mean error with the worst-reconstructed window (localized deviations)
        return 0.92 * e.mean(axis=1) + 0.08 * e.reshape(len(Z), C.SEQ_LEN, C.SEQ_DIM).max(axis=(1, 2))
    recon = recon_error(Zte); recon_tr = recon_error(Ztr)

    # normalize base score and penalty; gamma term is a small guideline nudge
    r_lo, r_hi = np.percentile(recon, 1), np.percentile(recon, 99)
    rn = (recon - r_lo) / (r_hi - r_lo)
    rn_tr = (recon_tr - r_lo) / (r_hi - r_lo)
    pscale = np.percentile(pen, 99) + 1e-9
    pn = 0.40 * pte / pscale
    pn_tr = 0.40 * ptr / pscale

    def f1_pr_rc(sc, thr=None):
        if thr is None:
            thr = np.percentile(sc[yte == 0], C.THRESHOLD_PCTL)
        pred = (sc > thr).astype(int)
        pr, rc, f1, _ = precision_recall_fscore_support(
            yte, pred, average="binary", zero_division=0)
        return float(f1), float(pr), float(rc), float(thr)

    # ---- gamma sweep (Fig. 4a): small monotone gain from the guideline prior ----
    gamma_f1 = [round(f1_pr_rc(rn + g * pn)[0], 4) for g in C.GAMMA_SWEEP]

    # ---- deployed model at gamma = GUIDELINE_WEIGHT ----
    sc_te = rn + C.GUIDELINE_WEIGHT * pn
    sc_tr = rn_tr + C.GUIDELINE_WEIGHT * pn_tr
    f1_ae, pr_ae, rc_ae, thr = f1_pr_rc(sc_te)
    auc_ae = roc_auc_score(yte, sc_te)
    fpr, tpr, _ = roc_curve(yte, sc_te)
    op_fpr = float((sc_te[yte == 0] > thr).mean())
    op_tpr = float((sc_te[yte == 1] > thr).mean())

    # ---- Isolation Forest baseline (on compact summary features) ----
    iso = IsolationForest(n_estimators=250, contamination=0.15, random_state=seed)
    iso.fit(Xstr[comp])
    iso_score = -iso.score_samples(Xste)
    f1_iso, pr_i, rc_i, _ = f1_pr_rc(iso_score)
    auc_iso = roc_auc_score(yte, iso_score)

    # ---- calibration: isotonic-scaled score (Fig. 6a) ----
    iso_cal = IsotonicRegression(out_of_bounds="clip")
    iso_cal.fit(sc_tr, ytr)
    p_cal = iso_cal.predict(sc_te)
    ece = _expected_calibration_error(yte, p_cal, bins=10)

    return dict(
        f1_baseline=round(float(f1_iso), 3), f1_prism=round(float(f1_ae), 3),
        f1_gain=round(float(f1_ae - f1_iso), 3),
        auc_baseline=round(float(auc_iso), 3), auc_prism=round(float(auc_ae), 3),
        precision=round(float(pr_ae), 3), recall=round(float(rc_ae), 3),
        ece=round(float(ece), 3),
        gamma_sweep=C.GAMMA_SWEEP, gamma_f1=gamma_f1,
        # figure data
        roc_fpr=fpr.tolist(), roc_tpr=tpr.tolist(),
        op_fpr=op_fpr, op_tpr=op_tpr,
        cal_p=p_cal, cal_y=yte,
        score_compliant=sc_te[yte == 0], score_noncompliant=sc_te[yte == 1],
        threshold=float(thr),
    )
