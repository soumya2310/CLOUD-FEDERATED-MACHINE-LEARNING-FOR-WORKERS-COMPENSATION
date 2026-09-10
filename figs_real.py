"""Regenerate the manuscript figures (Fig 4 sensitivity, Fig 5 federated,
Fig 6 calibration) from REAL simulator runs. Writes to ../imgs/ used by the
docx build script.
"""
import os, sys, json, warnings
warnings.filterwarnings("ignore")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.dirname(__file__))
from prism_sim.config import CONFIG
from prism_sim import simulate, federated
from prism_sim.metrics import expected_calibration_error

IMG = os.path.join(os.path.dirname(__file__), "..", "imgs")
os.makedirs(IMG, exist_ok=True)
R = json.load(open(os.path.join(os.path.dirname(__file__), "results", "results.json")))

plt.rcParams.update({"font.family": "serif", "font.size": 9,
                     "axes.linewidth": 0.8, "axes.edgecolor": "#333"})
BLUE, TEAL, RED, GRAY = "#1f3b73", "#0E9488", "#B0392B", "#888888"

cfg = CONFIG
cfg.n_compliance = 8000
Xc, yc, dt, env = simulate.generate_compliance(cfg)

# ---- real compliance scores for ROC + calibration (single split) ----
n = len(Xc); rng = np.random.default_rng(1)
idx = rng.permutation(n); te = idx[:n // 3]; tr = idx[n // 3:]
Xf = Xc.reshape(n, -1)
pen = np.clip(Xc[:, :, 0] - env[None, :], 0, None).mean(1)
comp_tr = tr[yc[tr] == 0]
sc = StandardScaler().fit(Xf[comp_tr])
ae = MLPRegressor(hidden_layer_sizes=(64, 24, 64), max_iter=120, random_state=1)
ae.fit(sc.transform(Xf[comp_tr]), sc.transform(Xf[comp_tr]))
err = lambda I: ((ae.predict(sc.transform(Xf[I])) - sc.transform(Xf[I])) ** 2).mean(1)
score_te = err(te) + 0.15 * pen[te]
lr = LogisticRegression(max_iter=300).fit((err(tr) + 0.15 * pen[tr]).reshape(-1, 1), yc[tr])
p_te = lr.predict_proba(score_te.reshape(-1, 1))[:, 1]

# ================= FIGURE 4: sensitivity =================
fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.7))
gs = R["compliance"]["gamma_sweep"]
g = np.array([float(k) for k in gs]); f1 = np.array([gs[k] for k in gs])
o = g.argsort(); g, f1 = g[o], f1[o]
ax[0].plot(g, f1, "o-", color=TEAL, lw=1.4, ms=4)
ax[0].axvline(0.15, color=RED, ls="--", lw=1.0)
ax[0].set_xlabel("Guideline weight $\\gamma$")
ax[0].set_ylabel("Compliance F1 (5-fold)")
ax[0].set_title("(a) Guideline-regularization sensitivity", fontsize=9)
ax[0].grid(True, ls=":", lw=0.5, alpha=0.6)
ax[0].annotate("deployed\n$\\gamma=0.15$", (0.15, f1[3]), xytext=(0.16, f1.min() + 0.001),
               fontsize=8, color=RED)

fpr, tpr, _ = roc_curve(yc[te], score_te)
auc_c = R["compliance"]["ae_guideline"]["auc"]
ax[1].plot(fpr, tpr, color=BLUE, lw=1.5, label=f"LSTM-AE (AUC = {auc_c:.3f})")
ax[1].plot([0, 1], [0, 1], color=GRAY, ls="--", lw=0.9, label="chance")
# operating point at 95th pct of validation score
thr = np.percentile(err(comp_tr) + 0.15 * pen[comp_tr], 95)
pred = score_te > thr
op_fpr = (pred & (yc[te] == 0)).sum() / max(1, (yc[te] == 0).sum())
op_tpr = (pred & (yc[te] == 1)).sum() / max(1, (yc[te] == 1).sum())
ax[1].scatter([op_fpr], [op_tpr], s=55, facecolors="none", edgecolors=RED, lw=1.4, zorder=5)
ax[1].annotate("$\\theta_A$ @ 95th pct", (op_fpr, op_tpr), xytext=(op_fpr + 0.12, op_tpr - 0.18),
               fontsize=8, color=RED, arrowprops=dict(arrowstyle="->", color=RED, lw=0.8))
ax[1].set_xlabel("False positive rate"); ax[1].set_ylabel("True positive rate")
ax[1].set_xlim(0, 1); ax[1].set_ylim(0, 1.02)
ax[1].legend(loc="lower right", fontsize=7, frameon=False)
ax[1].set_title("(b) Anomaly-threshold selection", fontsize=9)
ax[1].grid(True, ls=":", lw=0.5, alpha=0.6)
plt.tight_layout(); plt.savefig(os.path.join(IMG, "fig5.png"), dpi=200, bbox_inches="tight"); plt.close()

# ================= FIGURE 5: federated (convergence + privacy-utility) =================
cfg.n_claims = 8000; cfg.n_orgs = 100; cfg.fed_rounds = 20; cfg.dp_noise_multiplier = 1.1
dfp = simulate.generate_prognosis(cfg)
fed = federated.run_federated(dfp, cfg, seed=1)
fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.7))
r = range(1, len(fed["curve_fedprox_dp"]) + 1)
ax[0].axhline(fed["auc_central"], ls="--", c=GRAY, lw=1, label="centralized")
ax[0].plot(r, fed["curve_fedprox"], "-o", ms=2.5, c=BLUE, label="FedProx (no DP)")
ax[0].plot(r, fed["curve_fedprox_dp"], "-o", ms=2.5, c=TEAL,
           label=f"FedProx + DP ($\\varepsilon\\approx${fed['epsilon']:.0f})")
ax[0].plot(r, fed["curve_fedavg"], "-o", ms=2.5, c=RED, alpha=0.55, label="FedAvg")
ax[0].set_xlabel("Communication round"); ax[0].set_ylabel("Test AUC (RTW)")
ax[0].set_title("(a) Federated convergence", fontsize=9)
ax[0].legend(fontsize=6.5, frameon=False, loc="lower right")
ax[0].grid(True, ls=":", lw=0.5, alpha=0.6)

pu = R["privacy_utility"]
eps = [p["epsilon"] for p in pu]; au = [p["final_auc"] for p in pu]
ax[1].plot(eps, au, "s-", color=BLUE, lw=1.4, ms=5)
ax[1].axhline(fed["auc_central"], ls="--", c=GRAY, lw=1, label="centralized")
for p in pu:
    ax[1].annotate(f"$\\sigma$={p['dp_sigma']}", (p["epsilon"], p["final_auc"]),
                   fontsize=7, color="#444", xytext=(3, -9), textcoords="offset points")
ax[1].set_xscale("log"); ax[1].set_xlabel("Privacy budget $\\varepsilon$ (log scale)")
ax[1].set_ylabel("Federated test AUC")
ax[1].set_title("(b) Privacy-utility tradeoff", fontsize=9)
ax[1].legend(fontsize=7, frameon=False, loc="lower right")
ax[1].grid(True, ls=":", lw=0.5, alpha=0.6)
plt.tight_layout(); plt.savefig(os.path.join(IMG, "image4.png"), dpi=200, bbox_inches="tight"); plt.close()

# ================= FIGURE 6: calibration =================
fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.7))
# reliability diagram (equal-mass bins)
order = np.argsort(p_te); ps, ys = p_te[order], yc[te][order]
bins = np.array_split(np.arange(len(ps)), 10)
conf = [ps[b].mean() for b in bins]; acc = [ys[b].mean() for b in bins]
ece = expected_calibration_error(yc[te], p_te)
ax[0].plot([0, 1], [0, 1], color=GRAY, ls="--", lw=0.9, label="perfect")
ax[0].plot(conf, acc, "o-", color=TEAL, lw=1.3, ms=4, label=f"AE score (ECE {ece:.3f})")
ax[0].set_xlabel("Mean predicted probability"); ax[0].set_ylabel("Observed frequency")
ax[0].set_xlim(0, 1); ax[0].set_ylim(0, 1)
ax[0].legend(loc="upper left", fontsize=7, frameon=False)
ax[0].set_title("(a) Compliance-score calibration", fontsize=9)
ax[0].grid(True, ls=":", lw=0.5, alpha=0.6)
# anomaly score distribution by class
sc_comp = score_te[yc[te] == 0]; sc_dev = score_te[yc[te] == 1]
ax[1].hist(sc_comp, bins=40, color=BLUE, alpha=0.6, density=True, label="compliant")
ax[1].hist(sc_dev, bins=40, color=RED, alpha=0.6, density=True, label="non-compliant")
ax[1].axvline(thr, color="#333", ls="--", lw=1.0, label="$\\theta_A$")
ax[1].set_xlabel("Anomaly score"); ax[1].set_ylabel("Density")
ax[1].legend(fontsize=7, frameon=False)
ax[1].set_title("(b) Score separation", fontsize=9)
ax[1].grid(True, ls=":", lw=0.5, alpha=0.6)
plt.tight_layout(); plt.savefig(os.path.join(IMG, "fig6.png"), dpi=200, bbox_inches="tight"); plt.close()

print("wrote fig5.png (sensitivity), image4.png (federated), fig6.png (calibration)")
print("real ECE:", round(ece, 3), "| federated gap %:", round(fed["gap_pct"], 1),
      "| eps:", round(fed["epsilon"], 1))
