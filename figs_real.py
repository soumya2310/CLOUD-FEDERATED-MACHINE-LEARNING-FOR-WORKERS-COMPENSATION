#!/usr/bin/env python3
"""Regenerate the data-driven figures of the paper (Fig. 4, 5, 6) from the arrays
written by run_all.py. Each panel plots the real model outputs of the simulator.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(__file__), "results")
FIG = os.path.join(OUT, "figures")

NAVY = "#00274C"; BLUE = "#0072CE"; TEAL = "#00A19A"
RED = "#D9534F"; GRAY = "#8A8D8F"; GREEN = "#4C9A2A"; ORANGE = "#E08E0B"
plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.25,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 150})


def _d():
    return np.load(os.path.join(OUT, "_figdata.npz"), allow_pickle=True)


# ----------------------------------------------------------------------
def fig4(d):
    """(a) F1 vs guideline-regularization weight gamma; (b) ROC of the anomaly
    detector with the deployed operating point."""
    fig, ax = plt.subplots(1, 2, figsize=(9.2, 3.7))

    g, f1 = d["gamma_sweep"], d["gamma_f1"]
    ax[0].plot(g, f1, "-o", color=BLUE, lw=2, ms=5)
    gi = int(np.argmin(np.abs(g - 0.15)))
    ax[0].scatter([g[gi]], [f1[gi]], s=120, facecolors="none",
                  edgecolors=RED, lw=2, zorder=5, label=r"deployed $\gamma=0.15$")
    ax[0].set_xlabel(r"guideline-regularization weight $\gamma$")
    ax[0].set_ylabel("compliance F1")
    ax[0].set_title("(a) Guideline-regularization sensitivity", fontsize=9.5)
    ax[0].set_ylim(f1.min() - 0.004, f1.max() + 0.004)
    ax[0].legend(frameon=False, fontsize=8, loc="lower right")

    fpr, tpr = d["roc_fpr"], d["roc_tpr"]
    ax[1].plot(fpr, tpr, color=TEAL, lw=2.2, label=f"AE detector (AUC={float(d['auc_prism']):.3f})")
    ax[1].plot([0, 1], [0, 1], "--", color=GRAY, lw=1)
    ax[1].scatter([d["op_fpr"]], [d["op_tpr"]], s=90, color=RED, zorder=5,
                  label=r"operating point $\theta_A$ (95th pctl)")
    ax[1].set_xlabel("false-positive rate"); ax[1].set_ylabel("true-positive rate")
    ax[1].set_title("(b) Anomaly-detector ROC", fontsize=9.5)
    ax[1].legend(frameon=False, fontsize=8, loc="lower right")
    ax[1].set_xlim(-0.02, 1.02); ax[1].set_ylim(-0.02, 1.02)

    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig4_compliance.png"), bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------
def fig5(d):
    """(a) Federated convergence; (b) privacy-utility trade-off (AUC vs epsilon)."""
    fig, ax = plt.subplots(1, 2, figsize=(9.2, 3.7))
    r = d["rounds"]
    ax[0].plot(r, d["c_central"], "--", color=GRAY, lw=1.8, label="centralized (upper bound)")
    ax[0].plot(r, d["c_fedprox"], "-o", color=BLUE, lw=2, ms=3.5, label="FedProx (no DP)")
    ax[0].plot(r, d["c_fedavg"], "-^", color=GREEN, lw=1.6, ms=3.5, label="FedAvg")
    ax[0].plot(r, d["c_dp"], "-s", color=RED, lw=2, ms=3.5,
               label=r"FedProx + DP ($\sigma$=1.1)")
    ax[0].set_xlabel("communication round"); ax[0].set_ylabel("RTW test AUC")
    ax[0].set_title("(a) Federated convergence", fontsize=9.5)
    ax[0].legend(frameon=False, fontsize=7.5, loc="lower right")

    eps, auc, sig = d["sweep_eps"], d["sweep_auc"], d["sweep_sigma"]
    order = np.argsort(eps)
    ax[1].plot(eps[order], auc[order], "-o", color=NAVY, lw=2, ms=6)
    for e, a, s in zip(eps, auc, sig):
        ax[1].annotate(fr"$\sigma$={s}", (e, a), textcoords="offset points",
                       xytext=(6, -11), fontsize=7.5, color=GRAY)
    ax[1].set_xscale("log")
    ax[1].set_xlabel(r"privacy budget $\varepsilon$ (log scale, $\delta=10^{-5}$)")
    ax[1].set_ylabel("federated test AUC")
    ax[1].set_title("(b) Privacy-utility trade-off", fontsize=9.5)
    ax[1].invert_xaxis()   # tighter privacy (smaller epsilon) to the right

    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig5_federated.png"), bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------
def fig6(d):
    """(a) Reliability diagram (ECE); (b) anomaly-score distributions."""
    fig, ax = plt.subplots(1, 2, figsize=(9.2, 3.7))
    p, y = d["cal_p"], d["cal_y"]
    bins = np.linspace(0, 1, 11)
    idx = np.digitize(p, bins) - 1
    xs, ys = [], []
    for b in range(10):
        m = idx == b
        if m.sum() > 5:
            xs.append(p[m].mean()); ys.append(y[m].mean())
    ax[0].plot([0, 1], [0, 1], "--", color=GRAY, lw=1, label="perfect calibration")
    ax[0].plot(xs, ys, "-o", color=BLUE, lw=2, ms=5, label="PRISM (isotonic)")
    ax[0].set_xlabel("predicted non-compliance probability")
    ax[0].set_ylabel("observed frequency")
    ax[0].set_title(f"(a) Reliability diagram (ECE={float(d['ece']):.3f})", fontsize=9.5)
    ax[0].legend(frameon=False, fontsize=8, loc="upper left")
    ax[0].set_xlim(0, 1); ax[0].set_ylim(0, 1)

    sc, snc = d["score_comp"], d["score_noncomp"]
    lo = min(sc.min(), snc.min()); hi = max(np.percentile(sc, 99.5), np.percentile(snc, 99.5))
    b = np.linspace(lo, hi, 45)
    ax[1].hist(sc, bins=b, color=TEAL, alpha=0.65, density=True, label="compliant")
    ax[1].hist(snc, bins=b, color=RED, alpha=0.6, density=True, label="non-compliant")
    ax[1].axvline(float(d["threshold"]), color=NAVY, ls="--", lw=1.6,
                  label=r"threshold $\theta_A$")
    ax[1].set_xlabel("anomaly score"); ax[1].set_ylabel("density")
    ax[1].set_title("(b) Anomaly-score distributions", fontsize=9.5)
    ax[1].legend(frameon=False, fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig6_calibration.png"), bbox_inches="tight")
    plt.close(fig)


def make_all():
    d = _d()
    fig4(d); fig5(d); fig6(d)


if __name__ == "__main__":
    make_all()
    print("figures written to", FIG)
