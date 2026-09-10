"""Central configuration for the PRISM synthetic simulator.

All parameters are explicit and seeded so every reported number is reproducible.
Sizes are set to run in a few minutes on a laptop; scale N_CLAIMS up for the
full-size study reported in the paper.
"""
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class Config:
    seed: int = 20260706

    # ----- cohort sizes (scale these up for the full study) -----
    n_claims: int = 24000          # injury-prognosis cohort
    n_compliance: int = 16000      # labelled treatment-compliance sequences
    n_rehab_episodes: int = 6000   # rehabilitation MDP episodes
    seq_len: int = 30              # weekly events per compliance sequence

    # ----- prognosis: competing-risks structure -----
    # three competing outcomes: 0=full-duty RTW, 1=modified-duty RTW, 2=permanent disability
    horizon_weeks: int = 104       # administrative censoring horizon
    brier_horizon: int = 52
    # sector-specific baseline hazard scaling (non-IID across employers)
    sectors: List[str] = field(default_factory=lambda: [
        "construction", "manufacturing", "healthcare", "transportation",
        "retail", "administrative", "agriculture"])
    sector_weights: List[float] = field(default_factory=lambda: [
        0.16, 0.17, 0.15, 0.13, 0.14, 0.14, 0.11])
    n_jurisdictions: int = 12

    # target marginals used ONLY to validate fidelity (Table 3 analogue)
    target_mean_lost_days: float = 68.0
    target_perm_disability_rate: float = 0.060
    target_attorney_rate: float = 0.21
    target_modified_share: float = 0.42

    # ----- compliance -----
    noncompliance_rate: float = 0.15
    deviation_mix: Dict[str, float] = field(default_factory=lambda: {
        "overtreatment": 0.62, "delayed_auth": 0.28, "contraindicated": 0.10})
    ae_threshold_pct: float = 95.0   # anomaly threshold percentile on validation

    # ----- rehabilitation MDP -----
    n_actions: int = 6
    rl_episodes_train: int = 12000
    rl_eval_rollouts: int = 3000

    # ----- federated -----
    n_orgs: int = 100
    fed_rounds: int = 20
    fedprox_mu: float = 0.01
    dp_noise_multiplier: float = 1.1
    dp_clip: float = 1.0
    dp_delta: float = 1e-5

    # ----- evaluation -----
    n_folds: int = 5
    bootstrap_reps: int = 1000
    test_frac: float = 0.15
    val_frac: float = 0.15


CONFIG = Config()
