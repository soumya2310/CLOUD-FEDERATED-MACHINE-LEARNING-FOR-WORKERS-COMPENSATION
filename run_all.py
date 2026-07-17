#!/usr/bin/env python3
"""Run every PRISM domain end to end and write results/results.json plus the
per-domain CSV tables. Then call figs_real.py to regenerate Figures 4-6.

Usage:
    python run_all.py            # full cohorts (paper values, ~4-6 min CPU)
    PRISM_FAST=1 python run_all.py   # reduced cohorts smoke test (~1 min)
"""
import json, os, time, csv
import numpy as np
from prism_sim import (config as C, simulate, prognosis, compliance,
                       rehab, federated, fusion)

OUT = os.path.join(os.path.dirname(__file__), "results")
FIG = os.path.join(OUT, "figures")
TAB = os.path.join(OUT, "tables")
for d in (OUT, FIG, TAB):
    os.makedirs(d, exist_ok=True)


def _write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def main():
    t0 = time.time()
    print(f"PRISM simulator | seed={C.MASTER_SEED} | FAST={C.FAST}")

    # ---- Domain 1: injury prognosis ----
    print("[1/5] prognosis: generating cohort + training survival models ...")
    pro = simulate.make_prognosis_cohort()
    marg = simulate.cohort_marginals(pro)
    prog = prognosis.run(pro)
    print(f"      C-index {prog['c_index_baseline']} -> {prog['c_index_prism']} "
          f"(gain {prog['c_index_gain']}, 95% CI {prog['c_index_gain_ci']})")

    # ---- Domain 2: treatment compliance ----
    print("[2/5] compliance: training guideline-regularized autoencoder ...")
    comp_cohort = simulate.make_compliance_cohort()
    comp = compliance.run(comp_cohort)
    print(f"      F1 {comp['f1_baseline']} -> {comp['f1_prism']} | "
          f"ROC-AUC {comp['auc_baseline']} -> {comp['auc_prism']} | ECE {comp['ece']}")

    # ---- Domain 3: rehabilitation optimization ----
    print("[3/5] rehab: tabular Q-learning vs rule-based ...")
    reh = rehab.run()
    print(f"      cost reduction {reh['cost_reduction_pct']}% "
          f"(DS-fusion +{reh['ds_fusion_gain_pts']} pts)")

    # ---- Domain 4: federated learning + differential privacy ----
    print("[4/5] federated: FedProx + Gaussian DP ...")
    fed = federated.run()
    print(f"      central {fed['auc_centralized']} | FedProx+DP {fed['auc_fedprox_dp']} "
          f"| gap {fed['privacy_gap_pct']}% | eps={fed['epsilon_deployed']}")

    # ---- Domain 5: Dempster-Shafer fusion ----
    print("[5/5] fusion: Dempster-Shafer combination ...")
    fus = fusion.demo()
    print(f"      pignistic recovery index -> {fus['index']} {fus['pignistic']}")

    results = dict(
        seed=C.MASTER_SEED, fast=C.FAST,
        cohort_marginals={k: round(v, 2) for k, v in marg.items()},
        prognosis={k: v for k, v in prog.items() if not isinstance(v, np.ndarray)},
        compliance={k: v for k, v in comp.items()
                    if not isinstance(v, np.ndarray) and k not in
                    ("cal_p", "cal_y", "score_compliant", "score_noncompliant",
                     "roc_fpr", "roc_tpr")},
        rehab=reh, federated={k: v for k, v in fed.items()
                              if not k.startswith("curve_") and k != "privacy_sweep"},
        federated_privacy_sweep=fed["privacy_sweep"], fusion=fus,
        runtime_sec=round(time.time() - t0, 1),
    )
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    # ---- CSV tables ----
    _write_csv(os.path.join(TAB, "table3_cohort_marginals.csv"),
               ["metric", "value"], [[k, round(v, 2)] for k, v in marg.items()])
    _write_csv(os.path.join(TAB, "table5_performance.csv"),
               ["domain", "metric", "baseline", "prism", "gain"],
               [["prognosis", "C-index", prog["c_index_baseline"], prog["c_index_prism"], prog["c_index_gain"]],
                ["prognosis", "AUC", prog["auc_baseline"], prog["auc_prism"], round(prog["auc_prism"]-prog["auc_baseline"],3)],
                ["prognosis", "Brier", prog["brier_baseline"], prog["brier_prism"], round(prog["brier_prism"]-prog["brier_baseline"],3)],
                ["compliance", "F1", comp["f1_baseline"], comp["f1_prism"], comp["f1_gain"]],
                ["compliance", "ROC-AUC", comp["auc_baseline"], comp["auc_prism"], round(comp["auc_prism"]-comp["auc_baseline"],3)],
                ["rehab", "cost-reduction-%", 0.0, reh["cost_reduction_pct"], reh["cost_reduction_pct"]]])
    _write_csv(os.path.join(TAB, "table_federated_privacy.csv"),
               ["sigma", "epsilon", "test_auc"],
               [[s["sigma"], s["epsilon"], s["auc"]] for s in fed["privacy_sweep"]])

    # stash figure-data arrays for figs_real.py
    np.savez(os.path.join(OUT, "_figdata.npz"),
             gamma_sweep=np.array(comp["gamma_sweep"]), gamma_f1=np.array(comp["gamma_f1"]),
             roc_fpr=np.array(comp["roc_fpr"]), roc_tpr=np.array(comp["roc_tpr"]),
             op_fpr=comp["op_fpr"], op_tpr=comp["op_tpr"], auc_prism=comp["auc_prism"],
             cal_p=comp["cal_p"], cal_y=comp["cal_y"],
             score_comp=comp["score_compliant"], score_noncomp=comp["score_noncompliant"],
             threshold=comp["threshold"], ece=comp["ece"],
             rounds=np.array(fed["rounds"]),
             c_central=np.array(fed["curve_centralized"]),
             c_fedprox=np.array(fed["curve_fedprox"]),
             c_dp=np.array(fed["curve_fedprox_dp"]),
             c_fedavg=np.array(fed["curve_fedavg"]),
             sweep_eps=np.array([s["epsilon"] for s in fed["privacy_sweep"]]),
             sweep_auc=np.array([s["auc"] for s in fed["privacy_sweep"]]),
             sweep_sigma=np.array([s["sigma"] for s in fed["privacy_sweep"]]))

    print(f"\nwrote {OUT}/results.json and {TAB}/*.csv  ({results['runtime_sec']}s)")

    # ---- figures ----
    import figs_real
    figs_real.make_all()
    print(f"wrote figures to {FIG}/")


if __name__ == "__main__":
    main()
