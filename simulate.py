"""Synthetic workers'-compensation cohort generator.

Generates three coupled datasets from an explicit generative model:
  1. Injury-prognosis cohort  -> cause-specific Weibull competing risks
  2. Treatment-compliance sequences -> guideline manifold + deviation injection
  3. Rehabilitation episodes  -> stochastic recovery MDP (built in rehab.py)

Everything is driven by the config seed so the whole study is reproducible.
The generative parameters are chosen so marginals land near published-style
benchmarks; fidelity is *checked*, not assumed (see run_all.py / Table 3).
"""
import numpy as np
import pandas as pd


# latent covariates that drive both time-to-event and (later) treatment
COVARS = [
    "age", "comorbidity", "severity", "func_capacity", "psychosocial",
    "attorney", "prior_claims", "bmi", "sector_idx", "jurisdiction",
]


def _sector_draw(rng, cfg, n):
    idx = rng.choice(len(cfg.sectors), size=n, p=np.array(cfg.sector_weights))
    return idx


def generate_prognosis(cfg):
    """Return a DataFrame with covariates, observed time, event cause, and
    a latent 'recovery_trajectory' signal used to build the cross-domain H.

    Causes: 0 full-duty RTW, 1 modified-duty RTW, 2 permanent disability.
    Censoring: administrative at horizon_weeks.
    """
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n_claims

    age = np.clip(rng.normal(42, 11, n), 18, 70)
    comorbidity = rng.poisson(0.8, n).astype(float)
    severity = np.clip(rng.beta(2.0, 3.0, n), 0, 1)            # 0 mild .. 1 severe
    func_capacity = np.clip(rng.normal(0.65, 0.18, n), 0, 1)   # higher = better
    psychosocial = np.clip(rng.normal(0.4, 0.2, n), 0, 1)      # higher = more risk
    attorney = (rng.random(n) < (0.06 + 0.22 * severity + 0.14 * psychosocial)).astype(int)
    prior_claims = rng.poisson(0.5, n).astype(float)
    bmi = np.clip(rng.normal(28, 5, n), 16, 50)
    sector_idx = _sector_draw(rng, cfg, n)
    jurisdiction = rng.integers(0, cfg.n_jurisdictions, n)

    # sector modifies baseline hazard (non-IID structure for federation)
    sector_haz = np.array([1.0, 1.05, 0.95, 1.15, 0.9, 0.8, 1.2])[sector_idx]

    # linear predictor raising overall event intensity (shorter durations)
    lp = (
        -0.9 * severity - 0.6 * comorbidity / 3 + 0.8 * func_capacity
        - 0.5 * psychosocial - 0.015 * (age - 40) - 0.4 * attorney
        - 0.1 * prior_claims - 0.01 * (bmi - 28)
    )
    # cause-specific relative intensities (softmax-like over three outcomes)
    #   full-duty favoured by good function/low severity; permanent by opposite
    s_full = 1.1 + 1.0 * func_capacity - 1.2 * severity - 0.8 * psychosocial - 0.5 * attorney
    s_mod = 0.4 + 0.2 * severity - 0.3 * func_capacity
    s_perm = -3.2 + 2.0 * severity + 1.0 * psychosocial + 0.9 * attorney + 0.02 * (age - 40)
    S = np.vstack([s_full, s_mod, s_perm]).T
    P = np.exp(S - S.max(1, keepdims=True))
    P = P / P.sum(1, keepdims=True)              # cause probabilities (if event occurs)

    # Weibull time-to-event; scale shortened by exp(lp) and sector
    shape_k = 1.2
    base_scale = 9.0                              # weeks (most claims close in weeks)
    scale = base_scale * np.exp(-lp) / sector_haz
    t_event = scale * rng.weibull(shape_k, n)     # weeks
    cause = np.array([rng.choice(3, p=P[i]) for i in range(n)])
    # permanent-disability claims form the long tail
    t_event = t_event * np.where(cause == 2, 3.0, 1.0)

    # administrative censoring
    censored = t_event > cfg.horizon_weeks
    observed_t = np.where(censored, cfg.horizon_weeks, t_event)
    event = (~censored).astype(int)               # 1 if any event observed
    obs_cause = np.where(censored, -1, cause)      # -1 = censored

    # latent recovery-trajectory signal (ground truth the models will estimate)
    recovery = np.clip(
        0.6 * func_capacity - 0.5 * severity - 0.4 * psychosocial
        - 0.2 * (comorbidity / 3) + 0.15 * (cause == 0) - 0.2 * (cause == 2)
        + rng.normal(0, 0.1, n), -1, 1)
    recovery = (recovery - recovery.min()) / (np.ptp(recovery) + 1e-9)  # -> [0,1]

    df = pd.DataFrame({
        "age": age, "comorbidity": comorbidity, "severity": severity,
        "func_capacity": func_capacity, "psychosocial": psychosocial,
        "attorney": attorney, "prior_claims": prior_claims, "bmi": bmi,
        "sector_idx": sector_idx, "jurisdiction": jurisdiction,
        "time": observed_t, "event": event, "cause": obs_cause,
        "true_cause": cause, "recovery_latent": recovery,
    })
    return df


def rolling_features(df):
    """XGBoost feature-engineering layer: expand covariates with interactions
    and rolling-style aggregates that a claims pipeline would compute.
    Returns an (n, p) float matrix and the feature names.
    """
    x = df[COVARS].to_numpy(float).copy()
    feats = list(COVARS)
    extra, names = [], []
    # interaction / nonlinear expansions (stand in for 14/30/90-day windows)
    def add(col, name):
        extra.append(col); names.append(name)
    add(df["severity"] * df["comorbidity"], "sev_x_comorb")
    add(df["severity"] * (1 - df["func_capacity"]), "sev_x_lowfunc")
    add(df["psychosocial"] * df["attorney"], "psych_x_atty")
    add(df["age"] * df["severity"] / 40, "age_x_sev")
    add(np.log1p(df["prior_claims"]), "log_prior")
    add((df["bmi"] > 30).astype(float), "obese")
    add(df["func_capacity"] ** 2, "func_sq")
    add(df["severity"] ** 2, "sev_sq")
    X = np.column_stack([x] + extra)
    return X, feats + names


def generate_compliance(cfg):
    """Weekly treatment-intensity sequences with injected guideline deviations.

    Returns X (n, seq_len, n_channels), y (0 compliant / 1 non-compliant),
    dev_type array, and the ODG intensity envelope per step.
    """
    rng = np.random.default_rng(cfg.seed + 1)
    n, T = cfg.n_compliance, cfg.seq_len
    channels = 4  # treatment intensity, visits, meds, procedure-risk

    # ODG-style guideline envelope: intensity should decay over an episode
    envelope = 1.0 - 0.6 * (np.arange(T) / T)          # (T,)

    X = np.zeros((n, T, channels))
    y = np.zeros(n, int)
    dev_type = np.array(["compliant"] * n, dtype=object)

    n_bad = int(round(cfg.noncompliance_rate * n))
    bad_idx = rng.choice(n, size=n_bad, replace=False)
    is_bad = np.zeros(n, bool); is_bad[bad_idx] = True
    mix = cfg.deviation_mix
    dev_labels = rng.choice(list(mix.keys()), size=n, p=np.array(list(mix.values())))

    for i in range(n):
        base = envelope * rng.uniform(0.7, 1.0) + rng.normal(0, 0.05, T)
        visits = np.clip(base * rng.uniform(0.8, 1.2, T), 0, None)
        meds = np.clip(envelope * rng.uniform(0.6, 1.0) + rng.normal(0, 0.06, T), 0, None)
        proc_risk = np.clip(rng.normal(0.15, 0.05, T), 0, 1)
        intensity = np.clip(base, 0, None)

        if is_bad[i]:
            d = dev_labels[i]; dev_type[i] = d; y[i] = 1
            start = rng.integers(0, T - 4)
            if d == "overtreatment":
                intensity[start:] += rng.uniform(0.12, 0.30)    # mildly exceeds envelope
                visits[start:] += rng.uniform(0.10, 0.25)
            elif d == "delayed_auth":
                intensity[:start + 3] *= rng.uniform(0.45, 0.65)  # suppressed early care
                visits[:start + 3] *= rng.uniform(0.5, 0.7)
            else:  # contraindicated
                proc_risk[start:start + 3] += rng.uniform(0.20, 0.40)
        X[i] = np.column_stack([intensity, visits, meds, proc_risk])

    return X, y, dev_type, envelope


if __name__ == "__main__":
    from .config import CONFIG
    df = generate_prognosis(CONFIG)
    print("prognosis:", df.shape)
    print(df[["time", "event", "cause"]].describe().round(2).to_string())
    print("event rate:", df.event.mean().round(3),
          "| perm-disability share:", (df.true_cause == 2).mean().round(3))
    Xc, yc, dt, env = generate_compliance(CONFIG)
    print("compliance:", Xc.shape, "non-compliant:", yc.mean().round(3))
