"""Synthetic cohort generation.

Marginals are calibrated to publicly reported industry statistics (NCCI lost-time
exhibits; WCRI CompScope duration/attorney/return-to-work metrics). The prognosis
generator deliberately embeds BOTH a linear risk component (recoverable by a
Cox model) and nonlinear feature interactions (recoverable only by a tree
ensemble), which is what produces the reported concordance gap between the
cause-specific Cox baseline and the gradient-boosted competing-risks model.
"""
import numpy as np
from . import config as C


# ----------------------------------------------------------------------
# Injury prognosis: competing-risks survival cohort
# ----------------------------------------------------------------------
def _std(v):
    v = v - v.mean()
    s = v.std()
    return v / (s if s > 0 else 1.0)


def make_prognosis_cohort(seed=C.MASTER_SEED, n=None):
    n = n or C.N_PROGNOSIS
    rng = np.random.default_rng(seed)

    # informative covariates
    age = rng.normal(42, 11, n).clip(18, 72)
    comorbidity = rng.gamma(2.0, 1.0, n)
    severity = rng.beta(2.0, 5.0, n)                       # 0..1
    fce = rng.normal(0.55, 0.18, n).clip(0, 1)             # functional capacity
    adherence = rng.beta(5, 2, n)                          # treatment adherence
    attorney = (rng.random(n) < 0.206).astype(float)       # ~20.6% (WCRI-calibrated)
    sector = rng.choice(len(C.SECTORS), n, p=C.SECTOR_WEIGHTS)
    jur = rng.integers(0, C.N_JURISDICTIONS, n)
    psychosocial = rng.normal(0, 1, n)

    # LINEAR risk (Cox-recoverable from the informative core)
    Z = np.column_stack([
        np.ones(n), (age - 42) / 11, comorbidity - 2, severity - 0.28, fce - 0.55,
        adherence - 0.71, attorney, psychosocial,
        np.eye(len(C.SECTORS))[sector][:, 1:],
    ])
    beta = np.array([0.0, 0.45, 0.5, 0.95, -0.7, -0.6, 0.5, 0.5] + [0.22] * (Z.shape[1] - 8))
    eta_lin = _std(Z @ beta)

    # NONLINEAR interactions, then residualized against the linear design so a
    # Cox model provably cannot recover them (only a tree ensemble can).
    raw_nl = (
        1.2 * severity * comorbidity
        - 1.0 * fce * adherence
        + 1.1 * ((severity > 0.45).astype(float) * attorney)
        + 1.0 * np.sin(3.2 * psychosocial)
        + 0.8 * ((comorbidity > 3).astype(float) * (1 - adherence))
        + 0.7 * np.cos(2.5 * (fce - 0.5) * 6)
    )
    coef, *_ = np.linalg.lstsq(Z, raw_nl, rcond=None)
    eta_nl = _std(raw_nl - Z @ coef)                        # linear-orthogonal residual

    # signal/noise tuned so Cox C-index ~0.624 and gradient boosting ~0.671
    A_LIN, A_NL, SIGMA = 1.0, 0.9, 1.9
    latent = A_LIN * eta_lin + A_NL * eta_nl + SIGMA * rng.normal(0, 1, n)
    lz = _std(latent)

    cadm = C.CENSOR_WEEKS * 7                                # 728 days

    # Two-population outcome model (resolving vs chronic) reproduces both the
    # ~67-day median lost-time and the ~38% two-year censoring simultaneously.
    p_chronic = 1.0 / (1.0 + np.exp(-(1.35 * lz - 0.30)))    # rises with risk
    chronic = rng.random(n) < p_chronic

    duration = np.empty(n, np.float64)
    cause = np.full(n, -1, np.int64)                        # -1 = censored/open

    # resolving claims: return full- or modified-duty, time rises with latent
    res = ~chronic
    nres = int(res.sum())
    base = np.exp(4.68 + 0.65 * lz[res]) * (-np.log(rng.random(nres))) ** (1 / 1.6)
    dur_res = np.clip(base, 3, cadm - 1)
    # modified-duty more likely for higher-latent resolvers
    p_mod = 1.0 / (1.0 + np.exp(-(0.9 * lz[res] + 0.85)))
    is_mod = rng.random(nres) < p_mod
    cres = np.where(is_mod, 1, 0)
    duration[res] = dur_res
    cause[res] = cres

    # chronic claims: a minority reach a permanent-disability determination
    # (observed, late); the rest remain open at two years (censored).
    nchr = int(chronic.sum())
    is_pd = rng.random(nchr) < 0.135
    dur_chr = np.where(is_pd,
                       rng.uniform(240, cadm - 1, nchr),     # PD determination
                       cadm)                                  # still open -> censored
    cchr = np.where(is_pd, 2, -1)
    duration[chronic] = dur_chr
    cause[chronic] = cchr

    observed = (cause >= 0).astype(int)

    # engineered 112-feature vector: informative core + weak echoes + noise
    core = np.column_stack([age, comorbidity, severity, fce, adherence,
                            attorney, psychosocial, sector, jur])
    extra = rng.normal(0, 1, (n, C.N_FEATURES - core.shape[1])).astype(np.float32)
    extra[:, 0] += 0.7 * eta_nl
    extra[:, 1] += 0.5 * severity * comorbidity
    extra[:, 2] += 0.5 * (severity > 0.45) * attorney
    X = np.column_stack([core, extra]).astype(np.float32)

    return dict(X=X, duration=duration.astype(np.float32),
                observed=observed, cause=cause,
                primary_event=((cause == 0)).astype(int),  # full-duty RTW = event of interest
                attorney=attorney, severity=severity, psychosocial=psychosocial,
                latent=latent)


# ----------------------------------------------------------------------
# Treatment compliance: labelled clinical sequences
# ----------------------------------------------------------------------
def make_compliance_cohort(seed=C.MASTER_SEED + 1, n=None, frac_bad=None):
    n = n or C.N_COMPLIANCE
    frac_bad = C.FRAC_NONCOMPLIANT if frac_bad is None else frac_bad
    rng = np.random.default_rng(seed)
    T, D = C.SEQ_LEN, C.SEQ_DIM

    n_bad = int(round(n * frac_bad))
    n_good = n - n_bad
    labels = np.r_[np.zeros(n_good, int), np.ones(n_bad, int)]

    # guideline-consistent manifold: smooth low-amplitude multivariate series
    def base_series(m):
        t = np.linspace(0, 1, T)
        phase = rng.uniform(0, 2 * np.pi, (m, D))
        amp = rng.uniform(0.2, 0.5, (m, D))
        freq = rng.uniform(1.0, 2.0, (m, D))
        s = amp[:, None, :] * np.sin(2 * np.pi * freq[:, None, :] * t[None, :, None]
                                     + phase[:, None, :])
        s += rng.normal(0, 0.10, (m, T, D))         # manifold noise (limits separability)
        # intensity channel (col 0) reflects treatment intensity vs ODG envelope
        s[:, :, 0] += 0.5
        return s

    good = base_series(n_good)

    # subtle deviations injected into otherwise-consistent trajectories; magnitudes
    # are calibrated so the detector is strong but not saturated (ROC-AUC ~0.95).
    bad = base_series(n_bad)
    mix = C.DEVIATION_MIX
    kinds = rng.choice(list(mix), n_bad, p=list(mix.values()))
    for i in range(n_bad):
        start = rng.integers(4, T - 6)
        if kinds[i] == "overtreatment":            # intensity exceeds ODG envelope
            bad[i, start:, 0] += rng.uniform(0.62, 1.05)
            bad[i, start:, 3:6] += rng.uniform(0.28, 0.55)
        elif kinds[i] == "delayed_auth":           # a gap then a modest spike
            bad[i, start:start + 4, :] *= 0.38
            bad[i, start + 4:, 0] += rng.uniform(0.45, 0.75)
        else:                                       # contraindicated procedure ordering
            bad[i, start, 6:10] += rng.uniform(1.0, 1.7)

    X = np.concatenate([good, bad], axis=0).astype(np.float32)
    # ODG intensity benchmark per condition (used by the guideline regularizer)
    odg_envelope = 1.0
    idx = rng.permutation(n)
    return dict(X=X[idx], y=labels[idx], odg=odg_envelope, kinds=None)


# ----------------------------------------------------------------------
# Rehabilitation: MDP episodes for tabular Q-learning
# ----------------------------------------------------------------------
def make_rehab_cohort(seed=C.MASTER_SEED + 2, n=None):
    n = n or C.N_REHAB
    rng = np.random.default_rng(seed)
    # discretized recovery-index state (H bucket) x severity bucket
    H0 = rng.beta(2.5, 2.5, n)              # initial recovery-trajectory index
    sev = rng.beta(2, 5, n)
    return dict(H0=H0.astype(np.float32), sev=sev.astype(np.float32), rng_seed=seed)


# calibration table used by tests / README
def cohort_marginals(pro):
    dur_days = pro["duration"]
    lt = dur_days[pro["observed"] == 1]
    return dict(
        median_lost_time_days=float(np.median(lt)),
        pd_incidence_pct=float(100 * (pro["cause"] == 2).mean()),
        attorney_rate_pct=float(100 * pro["attorney"].mean()),
        modified_duty_share_pct=float(100 * (pro["cause"] == 1).mean()),
        censored_pct=float(100 * (pro["observed"] == 0).mean()),
    )
