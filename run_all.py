"""End-to-end PRISM simulation: runs every domain, computes REAL metrics,
and writes results tables + figures that mirror the paper's structure.

Usage:  python run_all.py            (default sizes, ~3-6 min)
        python run_all.py --fast     (small sizes for a quick smoke test)
"""
import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

from prism_sim.config import CONFIG
from prism_sim import simulate, prognosis, compliance, rehab, fusion, federated
from prism_sim.metrics import bootstrap_ci, wilcoxon_p, ks_fidelity

RES = os.path.join(os.path.dirname(__file__), "results")
TAB = os.path.join(RES, "tables")
FIG = os.path.join(RES, "figures")
for d in (RES, TAB, FIG):
    os.makedirs(d, exist_ok=True)


def savetab(name, df):
    df.to_csv(os.path.join(TAB, name), index=False)
    return df


def main(fast=False):
    t0 = time.time()
    cfg = CONFIG
    if fast:
        cfg.n_claims = 4000; cfg.n_compliance = 3000
        cfg.n_orgs = 30; cfg.fed_rounds = 10
        cfg.rl_episodes_train = 4000; cfg.rl_eval_rollouts = 1000
        cfg.bootstrap_reps = 300; cfg.n_folds = 3
    print(f"[cfg] claims={cfg.n_claims} compliance={cfg.n_compliance} "
          f"orgs={cfg.n_orgs} rounds={cfg.fed_rounds} folds={cfg.n_folds}")
    results = {}

    # ---------------- 1. cohort + fidelity ----------------
    print("[1/6] generating cohort + fidelity ...")
    df = simulate.generate_prognosis(cfg)
    ev = df[df.event == 1]

    def row(name, syn, tgt):
        rel = 100.0 * abs(syn - tgt) / abs(tgt)
        return [name, round(syn, 3), tgt, round(rel, 1)]
    fidelity = pd.DataFrame([
        row("Median lost-time duration (days)", float(ev.time.median() * 7), cfg.target_mean_lost_days),
        row("Permanent-disability incidence", float((df.true_cause == 2).mean()), cfg.target_perm_disability_rate),
        row("Attorney-involvement rate", float(df.attorney.mean()), cfg.target_attorney_rate),
        row("Modified-duty share of RTW", float((df.true_cause == 1).sum() / df.true_cause.isin([0, 1]).sum()), cfg.target_modified_share),
    ], columns=["quantity", "synthetic", "target", "rel_error_pct"])
    savetab("table3_fidelity.csv", fidelity)
    results["fidelity"] = fidelity.to_dict("records")
    # Cross-seed KS stability of the duration distribution (two-sample KS,
    # not applicable to scalar proportions — see Section VI-A)
    from prism_sim.metrics import ks_fidelity
    from scipy import stats
    df2 = simulate.generate_prognosis(Config(seed=cfg.seed + 999))
    d1 = df[df.event == 1].time.values * 7
    d2 = df2[df2.event == 1].time.values * 7
    rng_ks = np.random.default_rng(0)
    s1 = rng_ks.choice(d1, min(4000, len(d1)), replace=False)
    s2 = rng_ks.choice(d2, min(4000, len(d2)), replace=False)
    ks_result = stats.ks_2samp(s1, s2)
    results["ks_cross_seed"] = {"stat": round(float(ks_result.statistic), 4),
                                 "p": round(float(ks_result.pvalue), 3)}
    print(f"   KS cross-seed duration: stat={ks_result.statistic:.4f} p={ks_result.pvalue:.3f}")
    print(fidelity.to_string(index=False))

    # ---------------- 2. compliance ----------------
    print("[2/6] compliance detection + guideline ablation ...")
    Xc, yc, dt, env = simulate.generate_compliance(cfg)
    comp = compliance.evaluate_compliance(Xc, yc, env, gamma=0.15, seed=1, folds=cfg.n_folds)
    cp = comp["point"]
    # gamma sensitivity sweep (real)
    gammas = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
    gamma_f1 = []
    for g in gammas:
        rg = compliance.evaluate_compliance(Xc, yc, env, gamma=g, seed=1, folds=cfg.n_folds)
        gamma_f1.append(rg["point"]["f1"])
    # Paired Wilcoxon: AE+guideline vs Isolation Forest fold F1
    wil_p = wilcoxon_p(np.array(comp["f1"]), np.array(comp["f1_if"]))
    print(f"   Wilcoxon AE vs IsoForest: p={wil_p:.4f}")
    results["compliance"] = {
        "ae_guideline": cp, "gamma_sweep": dict(zip(map(str, gammas), gamma_f1)),
        "f1_ci": bootstrap_ci((comp["f1"],), lambda a: a.mean(), reps=cfg.bootstrap_reps),
        "wilcoxon_ae_vs_isoforest_p": float(wil_p),
    }
    print(f"   AE+guideline F1={cp['f1']:.3f} AUC={cp['auc']:.3f} ECE={cp['ece']:.3f} "
          f"| ablated F1={cp['f1_abl']:.3f} | IsoForest F1={cp['f1_if']:.3f}")

    # ---------------- 3. cross-domain H via DS fusion ----------------
    print("[3/6] Dempster-Shafer recovery index H ...")
    prog_risk = prognosis.prognosis_risk_scores(df, seed=1)
    comp_norm = compliance.compliance_normality_for_claims(df, cfg, seed=1)
    rehab_stage = df.func_capacity.to_numpy()
    H, conflict = fusion.recovery_index(prog_risk, comp_norm, rehab_stage)
    results["fusion"] = {"H_mean": float(H.mean()), "mean_conflict": conflict}
    print(f"   H mean={H.mean():.3f}  mean-conflict K={conflict:.3f}")

    # ---------------- 4. prognosis: baseline / full / full+H ----------------
    print("[4/6] prognosis competing-risks (baseline / full / full+H) ...")
    base = prognosis.evaluate_prognosis(df, "baseline", seed=1, folds=cfg.n_folds)
    full = prognosis.evaluate_prognosis(df, "full", seed=1, folds=cfg.n_folds)
    fullH = prognosis.evaluate_prognosis(df, "full", H=H, seed=1, folds=cfg.n_folds)

    def ci(vec):
        return bootstrap_ci((vec,), lambda a: a.mean(), reps=cfg.bootstrap_reps)

    perf = pd.DataFrame([
        ["RTW concordance (baseline)", *ci(base["cindex_folds"])],
        ["RTW concordance (PRISM full)", *ci(full["cindex_folds"])],
        ["RTW concordance (PRISM full + H)", *ci(fullH["cindex_folds"])],
        ["Cause-specific AUC (baseline)", *ci(base["auc_folds"])],
        ["Cause-specific AUC (PRISM full+H)", *ci(fullH["auc_folds"])],
        ["Brier @52w (baseline)", *ci(base["brier_folds"])],
        ["Brier @52w (PRISM full+H)", *ci(fullH["brier_folds"])],
    ], columns=["metric", "estimate", "ci_lo", "ci_hi"])
    savetab("table5_prognosis.csv", perf.round(4))

    # rigorous significance: bootstrap the C-index DIFFERENCE on pooled
    # out-of-fold predictions (same subjects, paired), 95% CI of the gain.
    from lifelines.utils import concordance_index
    t_all = fullH["oof_time"]; e_all = fullH["oof_event0"]
    rb = base["oof_risk"]; rH = fullH["oof_risk"]
    mask = ~(np.isnan(rb) | np.isnan(rH))
    t_all, e_all, rb, rH = t_all[mask], e_all[mask], rb[mask], rH[mask]

    def cdiff(sample_idx):
        cb = concordance_index(t_all[sample_idx], -rb[sample_idx], e_all[sample_idx])
        cH = concordance_index(t_all[sample_idx], -rH[sample_idx], e_all[sample_idx])
        return cH - cb
    rng2 = np.random.default_rng(7)
    reps = min(300, cfg.bootstrap_reps)
    diffs = np.array([cdiff(rng2.choice(len(t_all), len(t_all), replace=True))
                      for _ in range(reps)])
    d_point = cdiff(np.arange(len(t_all)))
    d_lo, d_hi = np.percentile(diffs, [2.5, 97.5])
    sig = bool(d_lo > 0)
    results["prognosis"] = {
        "baseline_cindex": base["cindex"], "full_cindex": full["cindex"],
        "fullH_cindex": fullH["cindex"],
        "gain_fullH_vs_baseline": round(float(d_point), 4),
        "gain_ci": [round(float(d_lo), 4), round(float(d_hi), 4)],
        "significant_95ci": sig,
        "improvement_pts": round(100 * (fullH["cindex"] - base["cindex"]), 1),
    }
    print(perf.round(3).to_string(index=False))
    print(f"   pooled-OOF C-index gain (full+H vs baseline) = {d_point:.3f} "
          f"95% CI [{d_lo:.3f}, {d_hi:.3f}]  significant={sig}")

    # ablation table (real deltas)
    abl = pd.DataFrame([
        ["PRISM full+H (prognosis C-index)", round(fullH["cindex"], 3), "--"],
        ["  - cross-domain H", round(full["cindex"], 3), round(full["cindex"] - fullH["cindex"], 3)],
        ["  - engineered features (baseline)", round(base["cindex"], 3), round(base["cindex"] - fullH["cindex"], 3)],
        ["PRISM compliance F1 (guideline)", round(cp["f1"], 3), "--"],
        ["  - guideline term (gamma=0)", round(cp["f1_abl"], 3), round(cp["f1_abl"] - cp["f1"], 3)],
        ["  - AE (Isolation Forest)", round(cp["f1_if"], 3), round(cp["f1_if"] - cp["f1"], 3)],
    ], columns=["configuration", "value", "delta"])
    savetab("table7_ablation.csv", abl)

    # ---------------- 5. rehabilitation ----------------
    print("[5/6] rehabilitation RL policy vs rule-based (avg over seeds) ...")
    seeds = [1, 2, 3] if not fast else [1, 2]
    full_red = []; noH_red = []; gain = []
    for sd in seeds:
        rr = rehab.evaluate_rehab(cfg, seed=sd)
        full_red.append(rr["full"]["reduction_pct"])
        noH_red.append(rr["no_H"]["reduction_pct"])
        gain.append(rr["fusion_gain_pct"])
    rh = {"full": {"reduction_pct": float(np.mean(full_red))},
          "no_H": {"reduction_pct": float(np.mean(noH_red))},
          "fusion_gain_pct": float(np.mean(gain)),
          "reduction_sd": float(np.std(full_red)), "seeds": seeds}
    results["rehab"] = rh
    print(f"   cost reduction full={rh['full']['reduction_pct']:.1f}% "
          f"(+/-{rh['reduction_sd']:.1f}) no_H={rh['no_H']['reduction_pct']:.1f}% "
          f"fusion gain={rh['fusion_gain_pct']:.1f}pts")

    # ---------------- 6. federated + privacy-utility ----------------
    print("[6/6] federated FedProx + differential privacy ...")
    fed = federated.run_federated(df, cfg, seed=1)
    # real privacy-utility sweep
    sweep = []
    for sig in [0.5, 0.8, 1.1, 2.0]:
        cfg.dp_noise_multiplier = sig
        fr = federated.run_federated(df, cfg, seed=1)
        eps = fr["epsilon"]
        sweep.append([sig, round(eps, 2), round(fr["final_auc_dp"], 3), round(fr["gap_pct"], 1)])
    cfg.dp_noise_multiplier = 1.1
    pu = pd.DataFrame(sweep, columns=["dp_sigma", "epsilon", "final_auc", "gap_pct"])
    savetab("table_privacy_utility.csv", pu)
    results["federated"] = {k: fed[k] for k in
                            ["auc_central", "final_auc_dp", "gap_pct",
                             "rounds_to_converge", "epsilon", "delta"]}
    results["privacy_utility"] = pu.to_dict("records")
    print(pu.to_string(index=False))

    # ---------------- figures ----------------
    print("[fig] writing figures ...")
    _fig_convergence(fed)
    _fig_gamma(gammas, gamma_f1)
    _fig_privacy(pu)

    results["runtime_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(RES, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
    _print_summary(results)
    print(f"\nDone in {results['runtime_sec']}s. Outputs in {RES}/")


def _fig_convergence(fed):
    plt.figure(figsize=(6, 3.4))
    r = range(1, len(fed["curve_fedprox_dp"]) + 1)
    plt.axhline(fed["auc_central"], ls="--", c="#888", lw=1, label="centralized")
    plt.plot(r, fed["curve_fedprox"], "-o", ms=3, c="#2563A6", label="FedProx (no DP)")
    plt.plot(r, fed["curve_fedprox_dp"], "-o", ms=3, c="#0E9488", label=f"FedProx + DP (\u03b5\u2248{fed['epsilon']:.1f})")
    plt.plot(r, fed["curve_fedavg"], "-o", ms=3, c="#B0392B", alpha=.6, label="FedAvg")
    plt.xlabel("communication round"); plt.ylabel("test AUC (RTW)")
    plt.title("Federated convergence (real runs)"); plt.legend(fontsize=8, frameon=False)
    plt.grid(ls=":", lw=.5, alpha=.6); plt.tight_layout()
    plt.savefig(os.path.join(FIG, "convergence.png"), dpi=160); plt.close()


def _fig_gamma(gammas, f1):
    plt.figure(figsize=(4.4, 3.2))
    plt.plot(gammas, f1, "-o", c="#0E9488")
    best = int(np.argmax(f1))
    plt.scatter([gammas[best]], [f1[best]], s=70, facecolors="none", edgecolors="#B0392B", lw=1.5)
    plt.xlabel("guideline weight \u03b3"); plt.ylabel("compliance F1")
    plt.title("Guideline-regularization sensitivity"); plt.grid(ls=":", lw=.5, alpha=.6)
    plt.tight_layout(); plt.savefig(os.path.join(FIG, "gamma_sensitivity.png"), dpi=160); plt.close()


def _fig_privacy(pu):
    plt.figure(figsize=(4.4, 3.2))
    plt.plot(pu["epsilon"], pu["final_auc"], "-o", c="#2563A6")
    plt.xscale("log")
    plt.xlabel("privacy budget \u03b5 (log)"); plt.ylabel("federated test AUC")
    plt.title("Privacy-utility tradeoff (real)"); plt.grid(ls=":", lw=.5, alpha=.6)
    plt.tight_layout(); plt.savefig(os.path.join(FIG, "privacy_utility.png"), dpi=160); plt.close()


def _print_summary(r):
    print("\n" + "=" * 66)
    print("PRISM SIMULATION — REAL RESULTS SUMMARY")
    print("=" * 66)
    pg = r["prognosis"]; cp = r["compliance"]["ae_guideline"]; rh = r["rehab"]; fd = r["federated"]
    print(f"Prognosis  RTW C-index : baseline {pg['baseline_cindex']:.3f} -> "
          f"PRISM+H {pg['fullH_cindex']:.3f}  (+{pg['improvement_pts']} pts, "
          f"gain CI {pg['gain_ci']}, sig={pg['significant_95ci']})")
    print(f"Compliance F1          : AE+guideline {cp['f1']:.3f} | IsoForest {cp['f1_if']:.3f} | ECE {cp['ece']:.3f}")
    print(f"Rehab cost reduction   : {rh['full']['reduction_pct']:.1f}%  (DS-fusion adds {rh['fusion_gain_pct']:.1f} pts)")
    print(f"Federated (DP)         : central AUC {fd['auc_central']:.3f}, "
          f"DP-final {fd['final_auc_dp']:.3f}, gap {fd['gap_pct']:.1f}%, \u03b5\u2248{fd['epsilon']:.1f}")
    print("=" * 66)


if __name__ == "__main__":
    main(fast="--fast" in sys.argv)
