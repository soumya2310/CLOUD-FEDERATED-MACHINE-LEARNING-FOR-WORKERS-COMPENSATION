"""Treatment-compliance domain: reconstruction-based anomaly detection.

A feed-forward autoencoder (reference implementation of the sequence
autoencoder; swap in a torch LSTM-AE for the deep variant) is trained on
compliant sequences only. Anomaly score = reconstruction error, optionally
augmented by a guideline-regularization penalty that flags care exceeding the
ODG intensity envelope. Reports REAL F1 / precision / recall / ROC-AUC / ECE
and a real ablation of the guideline term. Baseline = Isolation Forest.
"""
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression

from .metrics import f1_prec_rec, auc, expected_calibration_error


def _flatten(X):
    return X.reshape(X.shape[0], -1)


def _guideline_penalty(X, envelope):
    """Per-sequence excess of treatment intensity over the ODG envelope."""
    intensity = X[:, :, 0]                      # channel 0
    excess = np.clip(intensity - envelope[None, :], 0, None)
    return excess.mean(axis=1)                  # (n,)


def evaluate_compliance(X, y, envelope, gamma=0.15, seed=0,
                        thr_pct=95.0, folds=5):
    """Cross-validated compliance detection. Returns fold metrics for the
    guideline-regularized AE, the ablated AE (gamma=0), and IsolationForest.
    """
    rng = np.random.default_rng(seed)
    n = len(X)
    Xf = _flatten(X)
    pen = _guideline_penalty(X, envelope)
    idx = np.arange(n); rng.shuffle(idx)
    fold_id = np.array_split(idx, folds)

    out = {k: [] for k in ["f1", "prec", "rec", "auc", "ece",
                           "f1_abl", "auc_abl", "f1_if", "auc_if"]}
    for f in range(folds):
        te = fold_id[f]
        tr = np.concatenate([fold_id[g] for g in range(folds) if g != f])
        # split train into fit (compliant only) + validation (for threshold)
        tr_comp = tr[y[tr] == 0]
        n_val = int(0.25 * len(tr_comp))
        val = tr_comp[:n_val]; fit = tr_comp[n_val:]

        sc = StandardScaler().fit(Xf[fit])
        Zfit, Zval, Zte = sc.transform(Xf[fit]), sc.transform(Xf[val]), sc.transform(Xf[te])

        ae = MLPRegressor(hidden_layer_sizes=(64, 24, 64), activation="relu",
                          alpha=1e-4, max_iter=120, random_state=seed + f)
        ae.fit(Zfit, Zfit)

        def recon_err(Z):
            return ((ae.predict(Z) - Z) ** 2).mean(axis=1)

        err_val = recon_err(Zval)
        err_te = recon_err(Zte)

        # guideline-regularized score vs ablated score
        score_te = err_te + gamma * pen[te]
        score_val = err_val + gamma * pen[val]
        score_abl = err_te

        thr = np.percentile(score_val, thr_pct)
        pred = (score_te > thr).astype(int)
        f1, pr, rc = f1_prec_rec(y[te], pred)
        out["f1"].append(f1); out["prec"].append(pr); out["rec"].append(rc)
        out["auc"].append(auc(y[te], score_te))

        # calibrated probability -> ECE (Platt scaling on validation scores)
        yval = y[val]
        # validation has only compliant; build calibration set from tr instead
        tr_scores = recon_err(sc.transform(Xf[tr])) + gamma * pen[tr]
        lr = LogisticRegression(max_iter=200).fit(tr_scores.reshape(-1, 1), y[tr])
        p_te = lr.predict_proba(score_te.reshape(-1, 1))[:, 1]
        out["ece"].append(expected_calibration_error(y[te], p_te))

        # ablation gamma=0
        thr_a = np.percentile(err_val, thr_pct)
        pred_a = (score_abl > thr_a).astype(int)
        f1a, _, _ = f1_prec_rec(y[te], pred_a)
        out["f1_abl"].append(f1a); out["auc_abl"].append(auc(y[te], score_abl))

        # Isolation Forest baseline
        iso = IsolationForest(n_estimators=200, random_state=seed + f).fit(Zfit)
        s_if = -iso.score_samples(Zte)
        s_if_val = -iso.score_samples(Zval)
        thr_if = np.percentile(s_if_val, thr_pct)
        pred_if = (s_if > thr_if).astype(int)
        f1if, _, _ = f1_prec_rec(y[te], pred_if)
        out["f1_if"].append(f1if); out["auc_if"].append(auc(y[te], s_if))

    res = {k: np.array(v) for k, v in out.items()}
    res["point"] = {k: float(np.mean(v)) for k, v in res.items()}
    return res


def compliance_normality_for_claims(df, cfg, seed=0):
    """Generate one short treatment sequence per prognosis claim (parameterized
    by its covariates), train an AE on the 'normal' majority, and return a
    per-claim normality score in [0,1] for cross-domain fusion (H)."""
    rng = np.random.default_rng(seed + 7)
    n = len(df); T = cfg.seq_len
    envelope = 1.0 - 0.6 * (np.arange(T) / T)
    sev = df["severity"].to_numpy(); psy = df["psychosocial"].to_numpy()
    atty = df["attorney"].to_numpy()
    X = np.zeros((n, T, 4))
    for i in range(n):
        base = envelope * rng.uniform(0.7, 1.0) + rng.normal(0, 0.05, T)
        # higher severity/psychosocial/attorney -> more guideline drift
        drift = 0.4 * sev[i] + 0.3 * psy[i] + 0.2 * atty[i]
        if rng.random() < drift * 0.5:
            s = rng.integers(0, T - 4); base[s:] += rng.uniform(0.3, 0.8)
        X[i] = np.column_stack([np.clip(base, 0, None),
                                np.clip(base * rng.uniform(0.8, 1.2, T), 0, None),
                                np.clip(envelope + rng.normal(0, 0.06, T), 0, None),
                                np.clip(rng.normal(0.15, 0.05, T), 0, 1)])
    Xf = X.reshape(n, -1)
    pen = _guideline_penalty(X, envelope)
    sc = StandardScaler().fit(Xf)
    Z = sc.transform(Xf)
    ae = MLPRegressor(hidden_layer_sizes=(64, 24, 64), max_iter=80,
                      random_state=seed).fit(Z, Z)
    err = ((ae.predict(Z) - Z) ** 2).mean(1) + 0.15 * pen
    normality = 1.0 - (err - err.min()) / (np.ptp(err) + 1e-9)
    return normality
