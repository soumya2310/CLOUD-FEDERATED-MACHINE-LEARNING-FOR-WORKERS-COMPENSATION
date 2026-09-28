#!/usr/bin/env python3
"""Second-revision addendum: reviewer-requested robustness experiments.

Everything here is a REAL run of the released reference simulator
(prism_sim), extended with:

  A. Rehabilitation: 10 independent seeds, 95% CI of the cost reduction,
     paired per-episode significance vs. the rule-based baseline.
  B. Rehabilitation: sensitivity to reward weights (RTW bonus, chronic
     penalty, per-action cost scale) -- policy RE-TRAINED under each setting.
  C. Rehabilitation: robustness to MISSPECIFIED transition dynamics --
     policy trained under nominal dynamics, evaluated under perturbed
     dynamics (efficacy scale, H-informativeness, H observation noise,
     cost dispersion), rule-based baseline evaluated in the same perturbed
     environment.
  D. Fusion mechanism comparison with IDENTICAL inputs: Dempster-Shafer vs.
     weighted score averaging vs. Bayesian (log-odds) pooling vs. single
     best signal vs. oracle latent state vs. no index.
  E. Prognosis: stronger learned baselines under identical folds --
     Random Survival Forest (scikit-survival) and classical CoxPH.

Outputs: results/reviewer_addendum.json and results/tables/*.csv
"""
import json, os, time
import numpy as np, pandas as pd
from scipy import stats

from prism_sim.config import CONFIG as cfg
from prism_sim import rehab, fusion, simulate
from prism_sim.rehab import RehabMDP, ACTIONS, train_q, rule_based_policy

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
TAB = os.path.join(RES, "tables"); os.makedirs(TAB, exist_ok=True)
OUT = {}
t0 = time.time()

# --------------------------------------------------------------------------
# Perturbable environment (nominal == RehabMDP exactly)
# --------------------------------------------------------------------------
class PerturbedMDP(RehabMDP):
    def __init__(self, use_H=True, seed=0, eff_scale=1.0, match_slope=1.5,
                 h_noise=0.0, cost_disp=0.2, rtw_bonus=2.0, chronic_pen=6.0,
                 cost_scale=1.0, h_fn=None):
        super().__init__(use_H=use_H, seed=seed)
        self.eff_scale, self.match_slope, self.h_noise = eff_scale, match_slope, h_noise
        self.cost_disp, self.rtw_bonus, self.chronic_pen = cost_disp, rtw_bonus, chronic_pen
        self.cost_scale, self.h_fn = cost_scale, h_fn

    def reset(self):
        self.rec = self.rng.integers(0, 2)
        self.comp = self.rng.integers(0, self.n_comp)
        self.wk = 0
        self.base_cost = self.rng.uniform(1 - self.cost_disp, 1 + self.cost_disp)
        self._traj_q = self.rng.random()
        if self.use_H:
            q = self._traj_q
            if self.h_fn is not None:            # fused from noisy signals
                q = self.h_fn(q, self.rng)
            if self.h_noise > 0:                  # observation noise on H
                q = float(np.clip(q + self.rng.normal(0, self.h_noise), 0, 1))
            self.H = min(int(q * self.n_H), self.n_H - 1)
        else:
            self.H = 0
        return self._obs()

    def step(self, a):
        gain = {0: 0.10, 1: 0.28, 2: 0.18, 3: 0.22, 4: 0.30, 5: 0.26}[a]
        cost = {0: 0.2, 1: 0.9, 2: 1.1, 3: 0.7, 4: 0.5, 5: 1.2}[a] * self.base_cost * self.cost_scale
        traj = self._traj_q; s = self.match_slope
        match = 0.9
        if a in (1, 5):
            match = (0.2 + s) - s * traj
        elif a == 4:
            match = 0.2 + s * traj
        eff = self.eff_scale * gain * (0.6 + 0.4 * self.comp / (self.n_comp - 1)) * match
        if self.rng.random() < eff:
            self.rec = min(self.rec + 1, self.n_rec - 1)
        self.wk = min(self.wk + 1, self.n_week - 1)
        done = (self.rec >= self.n_rec - 1) or (self.wk >= self.n_week - 1)
        reward = -cost
        if done and self.rec >= self.n_rec - 1:
            reward += self.rtw_bonus
        elif done:
            reward -= self.chronic_pen
        return self._obs(), reward, done


def episode_costs(env, policy_fn, n, seed):
    env.rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        s = env.reset(); done = False; c = 0.0
        while not done:
            a = policy_fn(env, s)
            s, r, done = env.step(a)
            c += -r
        out.append(c)
    return np.array(out)


def run_pair(train_env, eval_env, seed, n_train=None, n_eval=None):
    """Train Q on train_env, evaluate learned vs rule-based on eval_env with
    common random numbers. Returns (reduction %, paired per-episode diff)."""
    n_train = n_train or cfg.rl_episodes_train
    n_eval = n_eval or cfg.rl_eval_rollouts
    Q = train_q(train_env, n_train, seed=seed)
    learned = lambda e, s: int(Q[s].argmax())
    rule = lambda e, s: rule_based_policy(e)
    c_rule = episode_costs(eval_env, rule, n_eval, seed + 1)
    c_learn = episode_costs(eval_env, learned, n_eval, seed + 1)
    red = 100.0 * (c_rule.mean() - c_learn.mean()) / c_rule.mean()
    return red, c_rule - c_learn


def tci(x):
    x = np.asarray(x, float); n = len(x)
    h = stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n)
    return float(x.mean()), float(x.std(ddof=1)), float(x.mean() - h), float(x.mean() + h)

# --------------------------------------------------------------------------
# A. seeds + significance
# --------------------------------------------------------------------------
print("[A] 10-seed rehabilitation replication ...")
SEEDS = list(range(1, 11))
full, noH, gain, pvals, wil = [], [], [], [], []
for sd in SEEDS:
    rF, dF = run_pair(PerturbedMDP(True, sd), PerturbedMDP(True, sd), sd)
    rN, _ = run_pair(PerturbedMDP(False, sd), PerturbedMDP(False, sd), sd)
    full.append(rF); noH.append(rN); gain.append(rF - rN)
    pvals.append(stats.ttest_1samp(dF, 0).pvalue)
    wil.append(stats.wilcoxon(dF).pvalue)
mF = tci(full); mN = tci(noH); mG = tci(gain)
OUT["A_seeds"] = dict(seeds=SEEDS, full=[round(x, 2) for x in full], noH=[round(x, 2) for x in noH],
                      full_mean_sd_ci=[round(v, 2) for v in mF], noH_mean_sd_ci=[round(v, 2) for v in mN],
                      gain_mean_sd_ci=[round(v, 2) for v in mG],
                      gain_ttest_p=float(stats.ttest_1samp(gain, 0).pvalue),
                      gain_positive_seeds=int(sum(g > 0 for g in gain)),
                      paired_ttest_p_max=float(max(pvals)), wilcoxon_p_max=float(max(wil)))
print(f"   full {mF[0]:.1f}% sd {mF[1]:.1f} CI [{mF[2]:.1f},{mF[3]:.1f}] | noH {mN[0]:.1f}% | "
      f"gain {mG[0]:.2f} CI [{mG[2]:.2f},{mG[3]:.2f}] p={OUT['A_seeds']['gain_ttest_p']:.4f} "
      f"| max paired p={max(pvals):.2e}")

# --------------------------------------------------------------------------
# B. reward-weight sensitivity (retrained)
# --------------------------------------------------------------------------
print("[B] reward-weight sensitivity ...")
rows = []
for name, kw in [("nominal", {}), ("RTW bonus x0.5", dict(rtw_bonus=1.0)), ("RTW bonus x2", dict(rtw_bonus=4.0)),
                 ("chronic penalty x0.5", dict(chronic_pen=3.0)), ("chronic penalty x1.5", dict(chronic_pen=9.0)),
                 ("action cost x0.5", dict(cost_scale=0.5)), ("action cost x1.5", dict(cost_scale=1.5))]:
    rf, rn = [], []
    for sd in SEEDS[:5]:
        rf.append(run_pair(PerturbedMDP(True, sd, **kw), PerturbedMDP(True, sd, **kw), sd)[0])
        rn.append(run_pair(PerturbedMDP(False, sd, **kw), PerturbedMDP(False, sd, **kw), sd)[0])
    rows.append([name, round(np.mean(rf), 1), round(np.std(rf, ddof=1), 1), round(np.mean(rn), 1), round(np.mean(rf) - np.mean(rn), 1)])
B = pd.DataFrame(rows, columns=["setting", "reduction_full_pct", "sd", "reduction_noH_pct", "H_gain_pts"])
B.to_csv(os.path.join(TAB, "table_reward_sensitivity.csv"), index=False); OUT["B_reward"] = B.to_dict("records")
print(B.to_string(index=False))

# --------------------------------------------------------------------------
# C. misspecified transition dynamics (train nominal, evaluate perturbed)
# --------------------------------------------------------------------------
print("[C] misspecified-dynamics robustness ...")
rows = []
for name, kw in [("nominal", {}), ("efficacy x0.7", dict(eff_scale=0.7)), ("efficacy x0.85", dict(eff_scale=0.85)),
                 ("efficacy x1.15", dict(eff_scale=1.15)), ("efficacy x1.3", dict(eff_scale=1.3)),
                 ("H half as informative (slope 0.75)", dict(match_slope=0.75)),
                 ("H uninformative (slope 0)", dict(match_slope=0.0)),
                 ("H observation noise sd 0.15", dict(h_noise=0.15)), ("H observation noise sd 0.30", dict(h_noise=0.30)),
                 ("cost dispersion x2", dict(cost_disp=0.4))]:
    rf, rn = [], []
    for sd in SEEDS[:5]:
        rf.append(run_pair(PerturbedMDP(True, sd), PerturbedMDP(True, sd, **kw), sd)[0])
        rn.append(run_pair(PerturbedMDP(False, sd), PerturbedMDP(False, sd, **kw), sd)[0])
    rows.append([name, round(np.mean(rf), 1), round(np.std(rf, ddof=1), 1), round(np.mean(rn), 1), round(np.mean(rf) - np.mean(rn), 1)])
C = pd.DataFrame(rows, columns=["evaluation_dynamics", "reduction_full_pct", "sd", "reduction_noH_pct", "H_gain_pts"])
C.to_csv(os.path.join(TAB, "table_dynamics_robustness.csv"), index=False); OUT["C_dynamics"] = C.to_dict("records")
print(C.to_string(index=False))

# --------------------------------------------------------------------------
# D. fusion mechanism comparison with identical inputs
# --------------------------------------------------------------------------
print("[D] fusion mechanism comparison ...")
NOISE = 0.25   # per-signal observation noise around the latent trajectory quality

def signals(q, rng):
    """Three noisy evidence sources, same construction as fusion.py expects:
    prognosis risk (high = bad), compliance normality (high = good),
    functional stage (high = good)."""
    prog = float(np.clip(1 - q + rng.normal(0, NOISE), 0, 1))
    comp = float(np.clip(q + rng.normal(0, NOISE), 0, 1))
    stage = float(np.clip(q + rng.normal(0, NOISE), 0, 1))
    return prog, comp, stage

def h_ds(q, rng):
    p, c, s = signals(q, rng)
    H, _ = fusion.recovery_index(np.array([p]), np.array([c]), np.array([s]))
    return float(H[0])

def h_avg(q, rng):
    p, c, s = signals(q, rng)
    return ((1 - p) + c + s) / 3.0

def h_bayes(q, rng):
    p, c, s = signals(q, rng)
    e = 1e-3
    lo = lambda x: np.log((x + e) / (1 - x + e))
    z = lo(1 - p) + lo(c) + lo(s)      # log-odds pooling (independent experts)
    return float(1 / (1 + np.exp(-z)))

def h_single(q, rng):
    p, c, s = signals(q, rng)
    return s                              # functional stage alone

def h_oracle(q, rng):
    return q

mechs = [("no index (unconditioned)", None, False), ("single signal (functional stage)", h_single, True),
         ("weighted score averaging", h_avg, True), ("Bayesian log-odds pooling", h_bayes, True),
         ("Dempster-Shafer + pignistic (PRISM)", h_ds, True), ("oracle latent trajectory", h_oracle, True)]
rows = []
for name, fn, useH in mechs:
    r = [run_pair(PerturbedMDP(useH, sd, h_fn=fn), PerturbedMDP(useH, sd, h_fn=fn), sd)[0] for sd in SEEDS[:5]]
    m = tci(r); rows.append([name, round(m[0], 1), round(m[1], 1), round(m[2], 1), round(m[3], 1)])
D = pd.DataFrame(rows, columns=["H_mechanism", "reduction_pct", "sd", "ci_lo", "ci_hi"])
D.to_csv(os.path.join(TAB, "table_fusion_comparison.csv"), index=False); OUT["D_fusion"] = D.to_dict("records")
print(D.to_string(index=False))

# --------------------------------------------------------------------------
# E. stronger prognosis baselines, identical folds
# --------------------------------------------------------------------------
print("[E] prognosis baselines: RSF, CoxPH, XGB-Cox (identical folds) ...")
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
from sksurv.ensemble import RandomSurvivalForest
from sksurv.util import Surv
from prism_sim import prognosis
df = simulate.generate_prognosis(cfg)
time_ = df["time"].to_numpy(float); cause = df["cause"].to_numpy(int); ev0 = (cause == 0)
Xfull, names = simulate.rolling_features(df)
rng = np.random.default_rng(1); idx = np.arange(len(df)); rng.shuffle(idx); folds = np.array_split(idx, cfg.n_folds)
oof = {k: np.full(len(df), np.nan) for k in ["xgb_full", "coxph_full", "rsf_full"]}
for f in range(cfg.n_folds):
    te = folds[f]; tr = np.concatenate([folds[g] for g in range(cfg.n_folds) if g != f])
    bst = prognosis._fit_cause_xgb(Xfull[tr], time_[tr], ev0[tr], 1 + f)
    oof["xgb_full"][te] = prognosis._risk(bst, Xfull[te])
    d = pd.DataFrame(Xfull[tr], columns=names); d["T"] = time_[tr]; d["E"] = ev0[tr].astype(int)
    cph = CoxPHFitter(penalizer=0.01).fit(d, "T", "E")
    oof["coxph_full"][te] = cph.predict_partial_hazard(pd.DataFrame(Xfull[te], columns=names)).values
    sub = rng.choice(tr, min(6000, len(tr)), replace=False)      # RSF on 6k subsample per fold (CPU budget)
    rsf = RandomSurvivalForest(n_estimators=100, min_samples_leaf=25, max_features="sqrt", n_jobs=-1, random_state=f)
    rsf.fit(Xfull[sub], Surv.from_arrays(ev0[sub], time_[sub]))
    oof["rsf_full"][te] = rsf.predict(Xfull[te])
    print(f"   fold {f} done ({time.time()-t0:.0f}s)")
def cidx(r): return float(concordance_index(time_, -r, ev0.astype(int)))
E = {k: round(cidx(v), 4) for k, v in oof.items()}
# bootstrap CI of XGB - RSF paired difference on OOF
rng2 = np.random.default_rng(7); n = len(df)
diffs = []
for _ in range(200):
    b = rng2.choice(n, n, replace=True)
    diffs.append(concordance_index(time_[b], -oof["xgb_full"][b], ev0[b].astype(int)) -
                 concordance_index(time_[b], -oof["rsf_full"][b], ev0[b].astype(int)))
E["xgb_minus_rsf_ci"] = [round(float(np.percentile(diffs, 2.5)), 4), round(float(np.percentile(diffs, 97.5)), 4)]
OUT["E_baselines"] = E
print(E)

OUT["runtime_sec"] = round(time.time() - t0, 1)
json.dump(OUT, open(os.path.join(RES, "reviewer_addendum.json"), "w"), indent=2)
print(f"Done in {OUT['runtime_sec']}s")
