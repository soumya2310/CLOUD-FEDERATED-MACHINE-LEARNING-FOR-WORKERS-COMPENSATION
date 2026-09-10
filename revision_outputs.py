#!/usr/bin/env python3
"""Addendum: computes reviewer-requested artifacts not in run_all.py.

Outputs:
  results/tables/table9_strata.csv  -- real per-stratum concordance
  results/revision_addendum.json    -- KS, Wilcoxon, CoxPH, FedAvg summary

Run AFTER run_all.py. Results are cached in results/_cache/ for resumability.
"""
import json, os, pickle, time
import numpy as np
import pandas as pd
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
from scipy import stats

from prism_sim.config import CONFIG as cfg
from prism_sim import simulate, prognosis, compliance, fusion, federated
from prism_sim.metrics import wilcoxon_p

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
CACHE = os.path.join(RES, "_cache")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(os.path.join(RES, "tables"), exist_ok=True)

def cached(name, fn):
    p = os.path.join(CACHE, name + ".pkl")
    if os.path.exists(p): return pickle.load(open(p,"rb"))
    v = fn(); pickle.dump(v, open(p,"wb")); return v

def main():
    t0 = time.time(); out = {}
    df = cached("cohort", lambda: simulate.generate_prognosis(cfg))

    def _fullH():
        pr = prognosis.prognosis_risk_scores(df, seed=1)
        cn = compliance.compliance_normality_for_claims(df, cfg, seed=1)
        H, K = fusion.recovery_index(pr, cn, df.func_capacity.to_numpy())
        fh = prognosis.evaluate_prognosis(df, "full", H=H, seed=1, folds=cfg.n_folds)
        return fh["oof_risk"], fh["oof_time"], fh["oof_event0"], float(K)
    r, t_oof, e, K = cached("fullH_oof", _fullH)

    # 1. Table 9 real stratum values
    rows = []
    sev = pd.qcut(df.severity, 3, labels=["Low","Mid","High"])
    for lab in ["Low","Mid","High"]:
        m = (sev==lab).values
        rows.append([f"{lab} severity (tertile)", int(m.sum()),
                     round(concordance_index(t_oof[m],-r[m],e[m]),3)])
    for lab, m in [("No attorney",df.attorney.values==0),
                   ("Attorney-involved",df.attorney.values==1)]:
        rows.append([lab, int(m.sum()),
                     round(concordance_index(t_oof[m],-r[m],e[m]),3)])
    psy = pd.qcut(df.psychosocial, 3, labels=["Low","Mid","High"])
    m = (psy=="High").values
    rows.append(["High psychosocial (tertile)", int(m.sum()),
                 round(concordance_index(t_oof[m],-r[m],e[m]),3)])
    t9 = pd.DataFrame(rows, columns=["stratum","N","rtw_cindex"])
    t9.to_csv(os.path.join(RES,"tables","table9_strata.csv"), index=False)
    out["per_stratum"] = t9.to_dict("records")
    print(t9.to_string(index=False))

    # 2. Classical CoxPH baseline
    def _cox():
        cx = df[["severity","age","func_capacity","time"]].copy()
        cx["e"] = (df.cause==0).astype(int)
        cph = CoxPHFitter(penalizer=0.01).fit(cx,"time","e")
        rk = cph.predict_partial_hazard(df[["severity","age","func_capacity"]]).values
        return float(concordance_index(df.time.values,-rk,(df.cause==0).astype(int).values))
    out["coxph_baseline_cindex"] = round(cached("coxph",_cox),4)
    print(f"Classical CoxPH baseline C-index: {out['coxph_baseline_cindex']}")

    # 3. Cross-seed KS stability (duration distribution)
    def _ks():
        from prism_sim.config import Config
        df2 = simulate.generate_prognosis(Config(seed=cfg.seed+999))
        d1 = df[df.event==1].time.values*7
        d2 = df2[df2.event==1].time.values*7
        rng = np.random.default_rng(0)
        s1 = rng.choice(d1,min(4000,len(d1)),replace=False)
        s2 = rng.choice(d2,min(4000,len(d2)),replace=False)
        ks = stats.ks_2samp(s1,s2)
        return dict(stat=round(float(ks.statistic),4), p=round(float(ks.pvalue),3))
    out["ks_cross_seed_duration"] = cached("ks",_ks)
    print(f"Cross-seed KS: {out['ks_cross_seed_duration']}")

    # 4. Wilcoxon: AE+guideline vs Isolation Forest fold F1
    def _wil():
        Xc, yc, _, env = simulate.generate_compliance(cfg)
        comp = compliance.evaluate_compliance(Xc,yc,env,gamma=0.15,seed=1,folds=cfg.n_folds)
        return dict(p=float(wilcoxon_p(np.array(comp["f1"]),np.array(comp["f1_if"]))),
                    f1_folds=[round(float(x),4) for x in comp["f1"]],
                    f1_if_folds=[round(float(x),4) for x in comp["f1_if"]])
    out["wilcoxon_ae_vs_isoforest"] = cached("wilcoxon",_wil)
    print(f"Wilcoxon AE vs IF: p={out['wilcoxon_ae_vs_isoforest']['p']:.4f}")

    # 5. FedAvg vs FedProx summary
    def _fed():
        fed = federated.run_federated(df, cfg, seed=1)
        return dict(fedprox_final=round(fed["curve_fedprox"][-1],4),
                    fedavg_final=round(fed["curve_fedavg"][-1],4),
                    max_abs_gap=round(float(np.max(np.abs(
                        np.array(fed["curve_fedprox"])-np.array(fed["curve_fedavg"])))),4))
    out["fedavg_vs_fedprox"] = cached("fed",_fed)
    print(f"FedAvg={out['fedavg_vs_fedprox']['fedavg_final']} FedProx={out['fedavg_vs_fedprox']['fedprox_final']} max|gap|={out['fedavg_vs_fedprox']['max_abs_gap']}")

    out["runtime_sec"] = round(time.time()-t0,1)
    json.dump(out, open(os.path.join(RES,"revision_addendum.json"),"w"), indent=2)
    print(f"Done in {out['runtime_sec']}s")

if __name__ == "__main__":
    main()
