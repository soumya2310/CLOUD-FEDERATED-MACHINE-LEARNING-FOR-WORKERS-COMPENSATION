import time, json, os, numpy as np, pandas as pd
from prism_sim.config import CONFIG as cfg
from prism_sim import simulate, prognosis
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
from sksurv.ensemble import RandomSurvivalForest
from sksurv.util import Surv
t0=time.time()
df = simulate.generate_prognosis(cfg)
time_ = df["time"].to_numpy(float); cause = df["cause"].to_numpy(int); ev0 = (cause == 0)
Xfull, names = simulate.rolling_features(df)
rng = np.random.default_rng(1); idx = np.arange(len(df)); rng.shuffle(idx); folds = np.array_split(idx, cfg.n_folds)
oof = {k: np.full(len(df), np.nan) for k in ["xgb_full", "coxph_full", "rsf_full"]}
for f in range(cfg.n_folds):
    te = folds[f]; tr = np.concatenate([folds[g] for g in range(cfg.n_folds) if g != f])
    bst = prognosis._fit_cause_xgb(Xfull[tr], time_[tr], ev0[tr], 1 + f)
    oof["xgb_full"][te] = prognosis._risk(bst, Xfull[te])
    d = pd.DataFrame(Xfull[tr], columns=names); d["T"] = time_[tr]; d["E"] = ev0[tr].astype(int)
    cph = CoxPHFitter(penalizer=0.01).fit(d, "T", "E")
    oof["coxph_full"][te] = cph.predict_partial_hazard(pd.DataFrame(Xfull[te], columns=names)).values
    sub = rng.choice(tr, 4000, replace=False)
    rsf = RandomSurvivalForest(n_estimators=50, min_samples_leaf=50, max_features="sqrt", random_state=f)
    rsf.fit(Xfull[sub], Surv.from_arrays(ev0[sub], time_[sub]))
    oof["rsf_full"][te] = rsf.predict(Xfull[te])
    print(f"fold {f} {time.time()-t0:.0f}s", flush=True)
def cidx(r): return float(concordance_index(time_, -r, ev0.astype(int)))
E = {k: round(cidx(v), 4) for k, v in oof.items()}
rng2 = np.random.default_rng(7); n = len(df); diffs=[]
for _ in range(100):
    b = rng2.choice(n, n, replace=True)
    diffs.append(concordance_index(time_[b], -oof["xgb_full"][b], ev0[b].astype(int)) - concordance_index(time_[b], -oof["rsf_full"][b], ev0[b].astype(int)))
E["xgb_minus_rsf_ci"] = [round(float(np.percentile(diffs, 2.5)), 4), round(float(np.percentile(diffs, 97.5)), 4)]
E["rsf_note"]="RSF: 50 trees, min_samples_leaf 50, sqrt features, fitted on a 4,000-claim subsample of each training fold (CPU budget); CoxPH: lifelines, penalizer 0.01, full engineered feature set; XGB-Cox: PRISM reference model, full features. All on identical 5 folds, concordance on pooled out-of-fold predictions for full-duty RTW."
json.dump(E, open("results/addendum_E.json","w"), indent=2); print(E, time.time()-t0)
