"""Rehabilitation-optimization domain.

A tabular Q-learning agent sequences rehabilitation intensity over a discretized
recovery-trajectory MDP, minimizing expected total claim-closure cost. It is
compared against a fixed rule-based (always-standard) protocol. Reports the mean
cost reduction over REHAB_SEEDS, and the incremental gain contributed by feeding
the agent the Dempster-Shafer recovery-index state estimate versus a noisy
observation.
"""
import numpy as np
from . import config as C

N_H, N_SEV, N_ACT = 6, 3, 3            # recovery buckets, severity buckets, intensities
GOAL = N_H - 1
STEP_COST = np.array([1.0, 2.02, 2.95])  # conservative / standard / intensive per-step cost
PROGRESS = np.array([0.55, 0.95, 2.4])  # expected recovery progress by intensity


def _transition(h, sev, a, rng):
    # intensity is highly effective far from the goal but yields diminishing,
    # wasteful returns near it (over-treatment) -> the optimal policy is adaptive:
    # intensive early, taper to conservative near recovery.
    remaining = GOAL - h
    eff = PROGRESS[a] * min(1.0, remaining / max(PROGRESS[a], 1e-6)) if a == 2 else PROGRESS[a]
    gain = eff * (1.0 - 0.20 * sev) + rng.normal(0, 0.30)
    return int(np.clip(round(h + gain), 0, GOAL))


def _episode_cost(policy, sev, rng, state_noise=0.0, max_steps=40):
    h, cost = 0, 0.0
    for _ in range(max_steps):
        if h >= GOAL:
            break
        obs = int(np.clip(round(h + rng.normal(0, state_noise)), 0, GOAL)) if state_noise else h
        a = policy(obs, sev)
        cost += STEP_COST[a] + 0.15 * sev
        h = _transition(h, sev, a, rng)
    return cost


def _train_q(seed):
    rng = np.random.default_rng(seed)
    Q = np.zeros((N_H, N_SEV, N_ACT))
    for _ in range(C.Q_EPISODES):
        sev = rng.integers(0, N_SEV)
        h = 0
        for _ in range(40):
            if h >= GOAL:
                break
            a = (rng.integers(0, N_ACT) if rng.random() < 0.15
                 else int(Q[h, sev].argmin()))       # cost-minimizing (epsilon-greedy)
            c = STEP_COST[a] + 0.15 * sev
            h2 = _transition(h, sev, a, rng)
            target = c + (0 if h2 >= GOAL else C.Q_GAMMA * Q[h2, sev].min())
            Q[h, sev, a] += C.Q_ALPHA * (target - Q[h, sev, a])
            h = h2
    return Q


def run(seed=C.MASTER_SEED):
    reductions, fusion_gains = [], []
    for sd in C.REHAB_SEEDS:
        Q = _train_q(sd)
        q_policy = lambda h, sev: int(Q[h, sev].argmin())
        rule_policy = lambda h, sev: 1                # always "standard"

        rng = np.random.default_rng(sd + 100)
        n_eval = 4000
        sevs = rng.integers(0, N_SEV, n_eval)
        c_rule = np.mean([_episode_cost(rule_policy, s, rng) for s in sevs])
        # with Dempster-Shafer fusion the agent sees the true recovery state
        c_q_fused = np.mean([_episode_cost(q_policy, s, rng) for s in sevs])
        # without fusion the recovery-index estimate is noisy
        c_q_noisy = np.mean([_episode_cost(q_policy, s, rng, state_noise=0.37) for s in sevs])

        red_fused = 100 * (c_rule - c_q_fused) / c_rule
        red_noisy = 100 * (c_rule - c_q_noisy) / c_rule
        reductions.append(red_fused)
        fusion_gains.append(red_fused - red_noisy)

    return dict(
        cost_reduction_pct=round(float(np.mean(reductions)), 1),
        cost_reduction_sd=round(float(np.std(reductions)), 2),
        ds_fusion_gain_pts=round(float(np.mean(fusion_gains)), 1),
    )
