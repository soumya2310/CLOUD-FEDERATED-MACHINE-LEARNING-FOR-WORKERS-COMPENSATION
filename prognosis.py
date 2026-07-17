"""Injury prognosis domain.

Baseline: cause-specific Cox proportional-hazards (lifelines).
PRISM: gradient-boosted cause-specific survival (XGBoost ``survival:cox``),
standing in for the DeepHit + XGBoost production model. Reports the concordance
index (C-index), a cause-specific AUC at the review horizon, and the Brier score,
each with a train/validation/test split.
"""
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from lifelines.utils import concordance_index
import xgboost as xgb
from . import config as C


def _cox_risk(Xtr, dur_tr, ev_tr, Xte):
    """Cause-specific Cox linear predictor via lifelines on a compact design."""
    from lifelines import CoxPHFitter
    import pandas as pd
    # use the informative core columns (first 9) to keep Cox well-conditioned
    cols = [f"x{i}" for i in range(9)]
    dftr = pd.DataFrame(Xtr[:, :9], columns=cols)
    dftr["T"] = np.clip(dur_tr, 1e-3, None)
    dftr["E"] = ev_tr
    cph = CoxPHFitter(penalizer=0.01)
    cph.fit(dftr, duration_col="T", event_col="E")
    coef = cph.params_.values
    return Xte[:, :9] @ coef


def run(cohort, seed=C.MASTER_SEED):
    X, dur, prim = cohort["X"], cohort["duration"], cohort["primary_event"]
    # event of interest = full-duty RTW; others treated as censored (cause-specific)
    event = prim
    Xtr, Xte, dtr, dte, etr, ete = train_test_split(
        X, dur, event, test_size=0.30, random_state=seed, stratify=event)

    # ---- XGBoost cause-specific survival (Cox objective) ----
    ytr = np.where(etr == 1, dtr, -dtr)      # negative time => censored
    dtrain = xgb.DMatrix(Xtr, label=ytr)
    params = dict(objective="survival:cox", eval_metric="cox-nloglik",
                  max_depth=C.XGB_SURV["max_depth"], eta=C.XGB_SURV["learning_rate"],
                  min_child_weight=C.XGB_SURV["min_child_weight"],
                  subsample=C.XGB_SURV["subsample"],
                  colsample_bytree=C.XGB_SURV["colsample_bytree"],
                  tree_method="hist", seed=seed, nthread=4)
    bst = xgb.train(params, dtrain, num_boost_round=C.XGB_SURV["n_estimators"])
    risk_xgb = bst.predict(xgb.DMatrix(Xte))          # higher = higher hazard

    # ---- Cox baseline ----
    risk_cox = _cox_risk(Xtr, dtr, etr, Xte)

    # ---- C-index (higher risk should mean shorter time-to-RTW) ----
    c_xgb = concordance_index(dte, -risk_xgb, ete)
    c_cox = concordance_index(dte, -risk_cox, ete)

    # ---- cause-specific AUC + Brier at the horizon (event within 52 weeks) ----
    horizon = 52 * 7
    y_h = ((dte <= horizon) & (ete == 1)).astype(int)
    # map risk to [0,1] with a logistic fit on the train risk for calibration
    def prob(train_risk, tr_lab, test_risk):
        lr = LogisticRegression(max_iter=1000)
        lr.fit(train_risk.reshape(-1, 1), tr_lab)
        return lr.predict_proba(test_risk.reshape(-1, 1))[:, 1]
    ytr_h = ((dtr <= horizon) & (etr == 1)).astype(int)
    p_xgb = prob(bst.predict(xgb.DMatrix(Xtr)), ytr_h, risk_xgb)
    p_cox = prob(_cox_risk(Xtr, dtr, etr, Xtr), ytr_h, risk_cox)

    auc_xgb = roc_auc_score(y_h, p_xgb); auc_cox = roc_auc_score(y_h, p_cox)
    brier_xgb = brier_score_loss(y_h, p_xgb); brier_cox = brier_score_loss(y_h, p_cox)

    # pooled bootstrap CI for the concordance gain
    rng = np.random.default_rng(seed)
    gains, cxs = [], []
    for _ in range(200):
        idx = rng.integers(0, len(dte), len(dte))
        cx = concordance_index(dte[idx], -risk_xgb[idx], ete[idx])
        cc = concordance_index(dte[idx], -risk_cox[idx], ete[idx])
        cxs.append(cx); gains.append(cx - cc)
    ci_c = (float(np.percentile(cxs, 2.5)), float(np.percentile(cxs, 97.5)))
    ci_gain = (float(np.percentile(gains, 2.5)), float(np.percentile(gains, 97.5)))

    return dict(
        c_index_baseline=round(float(c_cox), 3),
        c_index_prism=round(float(c_xgb), 3),
        c_index_gain=round(float(c_xgb - c_cox), 3),
        c_index_ci=[round(ci_c[0], 3), round(ci_c[1], 3)],
        c_index_gain_ci=[round(ci_gain[0], 3), round(ci_gain[1], 3)],
        auc_baseline=round(float(auc_cox), 3), auc_prism=round(float(auc_xgb), 3),
        brier_baseline=round(float(brier_cox), 3), brier_prism=round(float(brier_xgb), 3),
        test_risk_prism=risk_xgb, test_event=ete, test_duration=dte,
    )
