## Post-review addendum (final-files revision, Sept 2026)

Append this section to REPRODUCE_MAP.md.

| Paper item | Generated file | Produced by |
|---|---|---|
| Table 10, seed-replication block; Section VI-C ten-seed CI and paired tests | `results/addendum_A.json`, `results/reviewer_experiments_log.txt` | `reviewer_experiments.py` (section A, seeds 1-10) |
| Table 10, reward-weight block | `results/tables/table_reward_sensitivity.csv` | `reviewer_experiments.py` (section B, seeds 1-5) |
| Table 10, misspecified-dynamics block | `results/tables/table_dynamics_robustness.csv` | `reviewer_experiments.py` (section C) |
| Table 10, fusion-mechanism block | `results/tables/table_fusion_comparison.csv` | `reviewer_experiments.py` (section D) |
| Section VI-C: full-feature CoxPH 0.671, RSF 0.661, reduced CoxPH 0.629 | `results/addendum_E.json` | `exp_E.py` (identical 5 folds, cohort seed 20260706) |

Run from the parent directory of the checkout (the checkout must be importable as `prism_sim`,
exactly as for `run_all.py`), after `pip install -r prism_sim/requirements.txt scikit-survival`:

    python prism_sim/reviewer_experiments.py     # ~8 min CPU
    python prism_sim/exp_E.py                    # ~3 min CPU
