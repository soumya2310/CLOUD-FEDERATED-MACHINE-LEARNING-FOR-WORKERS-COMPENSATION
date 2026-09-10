# PRISM Synthetic Simulator

**GitHub Repository:** [https://github.com/soumya2310/CLOUD-FEDERATED-MACHINE-LEARNING-FOR-WORKERS-COMPENSATION](https://github.com/soumya2310/CLOUD-FEDERATED-MACHINE-LEARNING-FOR-WORKERS-COMPENSATION)


A runnable, reproducible simulation of the PRISM framework
(**P**rognosis, **R**ehabilitation, and **I**ntegrated compliance for
**S**afe **M**anagement of workers' compensation claims). It generates a
synthetic multi-employer claims cohort and runs every domain of the framework
end to end, producing **real, reproducible metrics** — not hand-set numbers.

Everything is seeded from `prism_sim/config.py`, so a given configuration
reproduces the same results on any machine.

## What this is (and is not)

This repository produces the numbers a simulation study is entitled to report:
outputs of an actual pipeline run on synthetic data. It is **not** a claim of
performance on real operational claims — that requires a prospective, in-boundary
federated validation, which is stated as future work.

To keep the whole study runnable on a laptop without a GPU, the neural
components are implemented as **faithful reference models** rather than the exact
deep architectures named in the paper. Each is a legitimate instance of the same
design; the deep variants can be swapped in where noted:

| Domain | Paper's named model | Reference model here | Deep variant to swap in |
|---|---|---|---|
| Prognosis | DeepHit + XGBoost competing risks | XGBoost cause-specific Cox (`survival:cox`) + engineered features | DeepHit (pycox/torch) |
| Compliance | Guideline-regularized LSTM autoencoder | Feed-forward autoencoder over sequence features + guideline penalty | LSTM-AE (torch) |
| Rehabilitation | PPO deep RL | Tabular Q-learning on the discretized recovery MDP | PPO (SB3/torch) |
| Federated | FedProx + DP-SGD | Logistic FedProx with gradient clipping + Gaussian DP (from scratch) | Same, deep model |
| Fusion | Dempster-Shafer over {On-Track, At-Risk, Critical} | Exact DS combination + pignistic transform | (identical) |

The metrics (concordance index, F1, ROC-AUC, Brier, ECE, cost reduction,
federated AUC, epsilon) are computed with standard libraries
(`lifelines`, `scikit-learn`, analytic RDP composition) from the actual runs.

## Install & run

```bash
pip install -r requirements.txt
python run_all.py            # full study (~5 min on a laptop CPU)
python run_all.py --fast     # quick smoke test (~30 s; RL is under-trained)
```

Outputs are written to `results/`:
- `results.json` — all metrics
- `tables/` — CSV tables mirroring the paper (fidelity, prognosis, ablation, privacy-utility)
- `figures/` — convergence, guideline sensitivity, privacy-utility (regenerated from real runs)

> Note: `--fast` shrinks the reinforcement-learning budget and under-trains the
> H-conditioned policy; use the full run for the rehabilitation numbers.

## Real results (full run, default config, seed 20260706)

These are the actual outputs of `python run_all.py` and should **replace** any
previously reported figures in the manuscript:

| Metric | Baseline | PRISM | Note |
|---|---|---|---|
| RTW concordance (C-index) | 0.624 | **0.671** | pooled-OOF gain +0.047, 95% CI [0.042, 0.051], significant |
| Cause-specific AUC | 0.618 | **0.649** | |
| Brier @ 52 wk | 0.272 | **0.257** | lower is better |
| Compliance F1 | 0.741 (Isolation Forest) | **0.813** (AE + guideline) | guideline term adds +0.003; ECE 0.016 |
| Rehab claim-cost reduction | — | **32.4%** | vs rule-based; DS-fusion adds +0.9 pts |
| Federated (σ=1.1) | 0.665 (centralized) | **0.620** | gap 6.7%, **ε ≈ 27.8**, δ=1e-5 |

### Honest findings that differ from the original manuscript

1. **Prognosis is hard.** Real RTW concordance is ~0.67, not 0.89. The
   engineered-feature model beats the reduced baseline significantly, but the
   absolute ceiling reflects genuine outcome noise.
2. **The cross-domain index H helps rehabilitation, not prognosis.** In this
   simulation H adds ~+0.9 cost-reduction points but nothing measurable on top
   of the engineered prognosis features. Report it where it helps.
3. **Strong differential privacy is expensive.** At σ=1.1 the composed budget is
   ε ≈ 28, not ε = 1.0. The privacy-utility sweep (`tables/table_privacy_utility.csv`)
   shows even σ=2.0 gives ε ≈ 13 at an 11% accuracy gap. Reaching ε=1 would
   require sub-sampling amplification and/or far fewer rounds; the manuscript's
   "ε=1.0 at 2.8% gap" is not supported and should be corrected.
4. **The guideline-regularization lift is small** (+0.003 F1) under these
   deviation settings — real, but modest; do not overstate it.

Scale `n_claims` up in `config.py` for the full-size cohort; the qualitative
conclusions are stable across sizes.

## Layout

```
prism_sim/
  config.py        parameters (seed, sizes, DP, RL, federated)
  simulate.py      cohort + compliance sequence generators
  prognosis.py     XGBoost cause-specific survival + C-index/AUC/Brier
  compliance.py    autoencoder anomaly detector + guideline term + baseline
  fusion.py        Dempster-Shafer recovery index H
  rehab.py         recovery MDP + Q-learning + rule-based baseline
  federated.py     FedProx + Gaussian DP + RDP epsilon accounting
  metrics.py       bootstrap CI, ECE, KS, Wilcoxon
run_all.py         orchestrates everything, writes tables + figures
```

## Manuscript–Code Reconciliation (Revision 2)

The following corrections were applied to the manuscript to match the actual
simulator outputs. Reviewers running the code will now find the manuscript
consistent with `config.py` and `results/results.json`.

| Manuscript claim (original) | Corrected value | Source |
|---|---|---|
| 180,000 injury-prognosis claims | **24,000** | `config.py: n_claims` |
| 24,000 compliance sequences (20,400/3,600) | **16,000 (13,600/2,400)** | `config.py: n_compliance, noncompliance_rate` |
| 8,000 rehabilitation episodes | **12,000 training + 3,000 eval** | `config.py: rl_episodes_train, rl_eval_rollouts` |
| 38.4% administrative censoring | **0.9%** | Measured from `generate_prognosis` output |
| "FedAvg failed to converge" | **FedAvg and noise-free FedProx converge identically** (both AUC 0.6637) | `results/results.json: curve_fedavg` |
| KS on scalar proportions (p > 0.10) | **Cross-seed KS on duration distribution** (stat=0.016, p=0.685) | `revision_outputs.py` |
| Table 9 stratum N values | **8,000 / 8,000 / 8,000 / 19,065 / 4,935 / 8,000** | `revision_outputs.py → table9_strata.csv` |
| Table 9 C-index values | **0.631 / 0.645 / 0.668 / 0.643 / 0.671 / 0.674** | `revision_outputs.py → table9_strata.csv` |
| "Cause-specific Cox baseline" | **Reduced-covariate gradient-boosted cause-specific survival** | `prognosis.py: evaluate_prognosis(feature_mode="baseline")` |
| 22 clinical channels | **4 channels in reference impl.** (22 in production LSTM-AE) | `simulate.py: generate_compliance` |

## New in this revision

- `revision_outputs.py`: additive, cached script computing Table 9 (real N and
  C-index values), CoxPH baseline comparison, cross-seed KS, and Wilcoxon test
- `run_all.py`: `ks_fidelity` and `wilcoxon_p` are now wired (previously
  imported but unused); both results written to `results.json`
- `results/tables/table9_strata.csv`: real per-stratum concordance table
