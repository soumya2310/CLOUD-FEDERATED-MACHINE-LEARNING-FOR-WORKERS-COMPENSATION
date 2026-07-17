# PRISM Synthetic Simulator

A runnable, seeded simulator for the **PRISM** framework — *Cloud-Federated
Machine Learning for Workers' Compensation Return-to-Work Prediction*. It
generates a synthetic multi-employer claims cohort and runs every domain of the
framework end to end, producing the **real, reproducible metrics and figures**
reported in the accompanying IEEE Access paper — not hand-set numbers.

Everything is seeded from `prism_sim/config.py`; a given configuration reproduces
the same results on any machine (up to minor BLAS/threading nondeterminism in
XGBoost, which does not change the conclusions).

## What this is — and is not

This repository produces exactly what a **simulation study** is entitled to
report: the outputs of an actual pipeline run on synthetic data. It is **not** a
claim of performance on real operational claims — that requires prospective,
in-boundary federated validation, which the paper states as future work.

To keep the whole study runnable on a laptop CPU, the neural components are
implemented as **faithful reference models** rather than the exact production
architectures named in the paper (e.g., a scikit-learn feed-forward autoencoder
stands in for the deep guideline-regularized sequence autoencoder; XGBoost
`survival:cox` stands in for the DeepHit + gradient-boosting competing-risks
model). The reference models reproduce the paper's reported behavior and
magnitudes.

## Quick start

```bash
pip install -r requirements.txt
python run_all.py            # full cohorts (paper sizes) — ~2-6 min on CPU
# or a ~1-minute smoke test on reduced cohorts:
PRISM_FAST=1 python run_all.py
```

Outputs land in `results/`:
- `results.json` — all metrics
- `tables/*.csv` — cohort marginals, performance table, privacy sweep
- `figures/fig4_compliance.png`, `fig5_federated.png`, `fig6_calibration.png`

To regenerate only the figures from an existing run: `python figs_real.py`.

## Package layout

```
prism_sim/
  config.py       seeds, cohort sizes, hyperparameters, calibration targets
  simulate.py     synthetic cohort generation (prognosis / compliance / rehab)
  prognosis.py    XGBoost competing-risks survival vs cause-specific Cox
  compliance.py   guideline-regularized autoencoder vs Isolation Forest
  rehab.py        tabular Q-learning vs rule-based protocol
  federated.py    from-scratch FedProx + Gaussian DP + Renyi-DP accounting
  fusion.py       exact Dempster-Shafer evidence combination
  metrics.py      bootstrap CIs and calibration error
run_all.py        orchestrates all domains -> results/
figs_real.py      regenerates Fig. 4-6 from the run
```

## Results reproduced by the reference run (seed 20260706, paper cohorts)

| Domain | Metric | Baseline | PRISM |
|---|---|---|---|
| Prognosis | C-index | 0.631 | **0.678** (gain +0.047, 95% CI [0.043, 0.051]) |
| Compliance | F1 | 0.740 (Isolation Forest) | **0.812** (gain +0.072) |
| Compliance | ROC-AUC / ECE | 0.917 | **0.955** / ECE 0.008 |
| Rehab | closure-cost reduction | — | **31.2%** (DS-fusion contribution +0.6 pts) |
| Federated | RTW test AUC | 0.666 (centralized) | **0.618** at sigma=1.1, epsilon~=28.7, gap 6-7% |

Synthetic cohort marginals are calibrated to publicly reported industry
statistics (NCCI lost-time exhibits; WCRI CompScope duration/attorney/return
metrics): median lost-time ~70 days, permanent-disability incidence ~6%,
attorney involvement ~21%, two-year censoring ~38%.

### Figures
- **Fig. 4** — (a) F1 vs guideline-regularization weight gamma (small monotone
  gain, deployed gamma=0.15); (b) anomaly-detector ROC with the theta_A operating
  point.
- **Fig. 5** — (a) federated convergence (centralized, FedProx, FedAvg,
  FedProx+DP); (b) privacy-utility trade-off (test AUC vs epsilon across
  sigma in {0.5, 0.8, 1.1, 2.0}).
- **Fig. 6** — (a) reliability diagram (ECE ~= 0.01); (b) anomaly-score
  distributions for compliant vs non-compliant episodes with the theta_A threshold.

## Reproducibility notes

- Master seed and every hyperparameter live in `prism_sim/config.py`.
- Differential-privacy budgets are reported with a Renyi-DP accountant over the
  federated rounds (`federated.rdp_epsilon`); sigma=1.1 -> epsilon~=28.7 and
  sigma=2.0 -> epsilon~=13.6 at delta=1e-5.
- Absolute figures may shift by a few thousandths across library/BLAS versions;
  the qualitative findings and reported gains are stable.

## License

MIT — see `LICENSE`.
