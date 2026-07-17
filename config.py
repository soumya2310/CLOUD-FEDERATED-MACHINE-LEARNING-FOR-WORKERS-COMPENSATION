"""Central configuration: master seed, cohort sizes, generator calibration, and
model hyperparameters. Everything downstream is derived from MASTER_SEED so a
given config reproduces the same results on any machine (up to BLAS/threading
nondeterminism in XGBoost, which is bounded and does not change conclusions)."""

MASTER_SEED = 20260706

# ---- Cohort sizes (paper values) ----
N_PROGNOSIS   = 180_000     # competing-risks claims
N_COMPLIANCE  = 24_000      # labelled 30-event clinical sequences
FRAC_NONCOMPLIANT = 0.15    # 3,600 non-compliant
N_REHAB       = 8_000       # active-claim RL episodes

# Set FAST=True (or env PRISM_FAST=1) for a ~1-minute smoke run on smaller cohorts.
import os
FAST = os.environ.get("PRISM_FAST", "0") == "1"
if FAST:
    N_PROGNOSIS, N_COMPLIANCE, N_REHAB = 30_000, 12_000, 4_000

# ---- Domain structure ----
SECTORS = ["construction", "manufacturing", "healthcare", "transportation",
           "retail", "administrative", "agriculture"]
SECTOR_WEIGHTS = [0.17, 0.20, 0.16, 0.12, 0.18, 0.10, 0.07]
N_JURISDICTIONS = 12
CENSOR_WEEKS = 104          # two-year statutory review horizon
N_FEATURES = 112            # engineered prognosis feature-vector width

# ---- Compliance deviation mix (of the non-compliant fraction) ----
DEVIATION_MIX = {"overtreatment": 0.62, "delayed_auth": 0.28, "contraindicated": 0.10}
SEQ_LEN = 30                # events per clinical sequence
SEQ_DIM = 22               # multivariate clinical observation dimension

# ---- Prognosis models ----
XGB_SURV = dict(objective="survival:cox", n_estimators=250, max_depth=4,
                learning_rate=0.05, min_child_weight=5, subsample=0.85,
                colsample_bytree=0.8, tree_method="hist")

# ---- Compliance autoencoder ----
AE_LATENT = 24
AE_HIDDEN = 64
GUIDELINE_WEIGHT = 0.15     # gamma; Fig. 4a sweep is 0.0 .. 0.30
GAMMA_SWEEP = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
THRESHOLD_PCTL = 95        # theta_A operating point

# ---- Rehabilitation (tabular Q-learning) ----
Q_ALPHA = 0.20
Q_GAMMA = 0.95
Q_EPISODES = N_REHAB
REHAB_SEEDS = [11, 23, 37]  # seeds for mean +/- s.d. of cost reduction

# ---- Federated learning ----
N_CLIENTS = 100
FED_ROUNDS = 15
FEDPROX_MU = 0.01
DP_CLIP = 1.0
DP_SIGMA = 1.1             # deployed noise multiplier
DP_DELTA = 1e-5
SIGMA_SWEEP = [0.5, 0.8, 1.1, 2.0]   # Fig. 5b privacy-utility sweep

# ---- Dempster-Shafer frame ----
DS_FRAME = ["On-Track", "At-Risk", "Critical"]

# ---- ODG intensity envelope (guideline benchmark) ----
ODG_ENVELOPE = 1.0
