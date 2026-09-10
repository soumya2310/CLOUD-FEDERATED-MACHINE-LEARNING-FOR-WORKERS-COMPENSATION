"""Injury-prognosis domain: competing-risks survival via cause-specific
gradient-boosted Cox models (XGBoost `survival:cox`).

Reports REAL metrics: cause-specific concordance index (lifelines),
time-truncated AUC, and Brier score at a horizon. A simple cause-specific
Cox on a reduced covariate set is the baseline; the full engineered feature
set (optionally + cross-domain index H) is the PRISM variant.
"""
import numpy as np
import xgboost as xgb
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
import pandas as pd

from .simulate import rolling_features, COVARS


def _cox_labels(time, is_event_cause):
    """xgboost survival:cox convention: positive label = event time,
    negative label = censoring time (right-censored for this cause)."""
    y = np.where(is_event_cause, time, -np.maximum(time, 1e-3))
    return y


def _fit_cause_xgb(X, time, is_event_cause, seed):
    d = xgb.DMatrix(X, label=_cox_labels(time, is_event_cause))
    params = dict(objective="survival:cox", eval_metric="cox-nloglik",
                  eta=0.05, max_depth=4, subsample=0.85, colsample_bytree=0.8,
                  min_child_weight=5, seed=seed)
    bst = xgb.train(params, d, num_boost_round=250, verbose_eval=False)
    return bst


def _risk(bst, X):
    return bst.predict(xgb.DMatrix(X))


def brier_at(time, event_cause, risk, horizon):
    """Simple (non-IPCW) Brier score at horizon for a cause, using a
    rank-calibrated risk->prob mapping. Real, comparable across models."""
    # observed label: experienced this cause by horizon
    y = ((time <= horizon) & event_cause).astype(float)
    # map risk to [0,1] via empirical rank (monotone, avoids scale issues)
    order = risk.argsort()
    p = np.empty_like(risk, float)
    p[order] = np.linspace(0.02, 0.98, len(risk))
    return float(np.mean((p - y) ** 2)), y, p


def evaluate_prognosis(df, feature_mode="full", H=None, seed=0, folds=5):
    """Cross-validated cause-specific concordance for full-duty RTW (cause 0),
    plus AUC and Brier at horizon. feature_mode in {baseline, full}.

    Returns dict of fold-vectors and point estimates.
    """
    from .config import CONFIG
    rng = np.random.default_rng(seed)
    n = len(df)
    time = df["time"].to_numpy(float)
    cause = df["cause"].to_numpy(int)          # -1 censored
    Xfull, names = rolling_features(df)
    if feature_mode == "baseline":
        # reduced covariate set -> weaker model (baseline)
        cols = [names.index(c) for c in ["severity", "age", "func_capacity"]]
        X = Xfull[:, cols]
    else:
        X = Xfull.copy()
        if H is not None:
            X = np.column_stack([X, H])

    idx = np.arange(n); rng.shuffle(idx)
    fold_id = np.array_split(idx, folds)
    cidx, aucs, briers = [], [], []
    oof_risk = np.full(n, np.nan)              # out-of-fold risk per subject
    from sklearn.metrics import roc_auc_score
    for f in range(folds):
        te = fold_id[f]
        tr = np.concatenate([fold_id[g] for g in range(folds) if g != f])
        is_c0_tr = (cause[tr] == 0)
        bst = _fit_cause_xgb(X[tr], time[tr], is_c0_tr, seed + f)
        r_te = _risk(bst, X[te])
        oof_risk[te] = r_te
        # cause-specific concordance for full-duty RTW on test fold
        ev = (cause[te] == 0).astype(int)
        # higher risk -> shorter time -> pass -risk to concordance_index
        try:
            c = concordance_index(time[te], -r_te, ev)
        except Exception:
            c = float("nan")
        cidx.append(c)
        # time-truncated AUC: event-by-horizon vs risk
        yb = ((time[te] <= CONFIG.brier_horizon) & (cause[te] == 0)).astype(int)
        if yb.sum() > 0 and yb.sum() < len(yb):
            aucs.append(roc_auc_score(yb, r_te))
        b, _, _ = brier_at(time[te], cause[te] == 0, r_te, CONFIG.brier_horizon)
        briers.append(b)
    return {
        "cindex_folds": np.array(cidx),
        "auc_folds": np.array(aucs),
        "brier_folds": np.array(briers),
        "cindex": float(np.nanmean(cidx)),
        "auc": float(np.nanmean(aucs)) if aucs else float("nan"),
        "brier": float(np.nanmean(briers)),
        "oof_risk": oof_risk,
        "oof_time": time,
        "oof_event0": (cause == 0).astype(int),
    }


def prognosis_risk_scores(df, seed=0):
    """Train on all data (for H construction) and return per-claim full-duty
    risk (higher = less likely / slower RTW), normalized to [0,1]."""
    time = df["time"].to_numpy(float)
    cause = df["cause"].to_numpy(int)
    X, _ = rolling_features(df)
    bst = _fit_cause_xgb(X, time, cause == 0, seed)
    r = _risk(bst, X)
    r = (r - r.min()) / (np.ptp(r) + 1e-9)
    return r
