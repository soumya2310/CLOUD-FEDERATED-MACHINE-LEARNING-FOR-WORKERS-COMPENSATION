# Reproducibility Map

This document ties every reported number, table, and figure in the paper to the
exact file that produces it, and records the environment for bit-for-bit
reproduction.

## Environment (reference run)

- Python **3.12.3**
- Pinned dependencies in `requirements.txt` (numpy 2.4.4, pandas 2.3.3,
  scipy 1.17.1, scikit-learn 1.8.0, xgboost 3.3.0, lifelines 0.30.3,
  matplotlib 3.10.8)
- Master seed: `20260706` (in `prism_sim/config.py`)
- Reference `results/results.json` SHA-256:
  `6f662e48a62cb310772dd630562e7f6cabc9389c5276b393d6c9f374c7c7e108`

Exact floating-point outputs depend on library and BLAS versions, so bit-for-bit
reproduction of the checksum assumes the pinned versions above (or the provided
`Dockerfile`). Qualitative conclusions are stable across versions and cohort
sizes.

## How to reproduce everything

```bash
bash reproduce.sh              # full run (~5 min CPU) -> results/
python figs_real.py            # regenerate the paper figures (Fig. 4-6)
# or, fully pinned:
docker build -t prism-sim . && docker run --rm -v "$PWD/results:/prism/results" prism-sim
```

## Tables

| Paper table | Generated file | Produced by |
|---|---|---|
| Table 3 — Distributional fidelity | `results/tables/table3_fidelity.csv` | `run_all.py` → `simulate.generate_prognosis` |
| Table 5 — Domain-specific performance | `results/tables/table5_prognosis.csv` (+ compliance/rehab metrics in `results.json`) | `prognosis.evaluate_prognosis`, `compliance.evaluate_compliance`, `rehab.evaluate_rehab` |
| Table 7 — Component ablation | `results/tables/table7_ablation.csv` | `run_all.py` (ablation section) |
| Table 8 — Bootstrap CIs & calibration | `results/results.json` keys `prognosis`, `compliance.ae_guideline`, `rehab` | `metrics.bootstrap_ci`, `metrics.expected_calibration_error` |
| Table 9 — Per-stratum performance | `results/tables/table9_strata.csv` (N: 8,000/8,000/8,000/19,065/4,935/8,000; C-index: 0.631/0.645/0.668/0.643/0.671/0.674) | `revision_outputs.py` → `per_stratum` block |
| Privacy–utility sweep | `results/tables/table_privacy_utility.csv` | `federated.run_federated` (σ sweep) |

## Figures

| Paper figure | Generated file | Produced by |
|---|---|---|
| Figure 4 — Hyperparameter sensitivity | `results/figures/fig5.png` | `figs_real.py` |
| Figure 5 — Federated convergence + privacy–utility | `results/figures/image4.png` | `figs_real.py` |
| Figure 6 — Calibration & score separation | `results/figures/fig6.png` | `figs_real.py` |
| Supporting single-panel versions | `results/figures/{convergence,gamma_sensitivity,privacy_utility}.png` | `run_all.py` |

> Note on figure filenames: the paper's manuscript build (`build_manuscript.js`)
> references `fig5.png` (sensitivity, paper Fig. 4), `image4.png` (federated,
> paper Fig. 5), and `fig6.png` (calibration, paper Fig. 6). The names are
> historical; the mapping above is authoritative.

## Headline numbers

All headline metrics (RTW concordance 0.671, cause-specific AUC 0.649,
Brier 0.257, compliance F1 0.813, rehab cost reduction 32.4%, federated gap and
ε at each σ) are stored in `results/results.json` and printed by `run_all.py`.
