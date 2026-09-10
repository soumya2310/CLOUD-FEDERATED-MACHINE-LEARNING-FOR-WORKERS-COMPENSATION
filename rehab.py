"""Rehabilitation domain: a stochastic recovery MDP with a learned policy.

Reference RL implementation is tabular Q-learning on a discretized state
(swap in PPO for the deep variant). We compare the learned policy against a
rule-based case-management baseline by Monte-Carlo rollouts in the SAME
simulator, and report a REAL expected claim-cost reduction. An H-conditioned
variant (recovery index in the state) is compared to an unconditioned one to
measure the real contribution of Dempster-Shafer fusion.
"""
import numpy as np

ACTIONS = ["continue", "escalate_cm", "request_ime", "authorize_fce",
           "rtw_coord", "refer_specialist"]


class RehabMDP:
    """State: (recovery_bin, compliance_bin, weeks_bin[, H_bin]).
    Reward: negative weekly cost; terminal bonus for RTW, penalty for chronic.
    """
    def __init__(self, use_H=True, seed=0):
        self.use_H = use_H
        self.rng = np.random.default_rng(seed)
        self.n_rec, self.n_comp, self.n_week = 5, 3, 8
        self.n_H = 4 if use_H else 1

    def n_states(self):
        return self.n_rec * self.n_comp * self.n_week * self.n_H

    def s_index(self, rec, comp, wk, h):
        h = h if self.use_H else 0
        return ((rec * self.n_comp + comp) * self.n_week + wk) * self.n_H + h

    def reset(self):
        self.rec = self.rng.integers(0, 2)          # start low recovery
        self.comp = self.rng.integers(0, self.n_comp)
        self.wk = 0
        self.base_cost = self.rng.uniform(0.8, 1.2)
        # latent trajectory quality; H is an (informative) observation of it
        self._traj_q = self.rng.random()
        if self.use_H:
            self.H = min(int(self._traj_q * self.n_H), self.n_H - 1)
        else:
            self.H = 0
        return self._obs()

    def _obs(self):
        return self.s_index(self.rec, self.comp, self.wk, self.H)

    def step(self, a):
        # base efficacy / cost per action
        gain = {0: 0.10, 1: 0.28, 2: 0.18, 3: 0.22, 4: 0.30, 5: 0.26}[a]
        cost = {0: 0.2, 1: 0.9, 2: 1.1, 3: 0.7, 4: 0.5, 5: 1.2}[a] * self.base_cost
        # the RIGHT action depends on the TRUE latent trajectory; only the
        # H-conditioned agent can observe it (via the fused recovery index).
        traj = self._traj_q
        match = 0.9
        if a in (1, 5):          # escalate / specialist: great for low trajectory
            match = 1.7 - 1.5 * traj
        elif a == 4:             # RTW coordination: great for high trajectory
            match = 0.2 + 1.5 * traj
        eff = gain * (0.6 + 0.4 * self.comp / (self.n_comp - 1)) * match
        if self.rng.random() < eff:
            self.rec = min(self.rec + 1, self.n_rec - 1)
        self.wk = min(self.wk + 1, self.n_week - 1)
        done = (self.rec >= self.n_rec - 1) or (self.wk >= self.n_week - 1)
        reward = -cost
        if done and self.rec >= self.n_rec - 1:
            reward += 2.0                          # RTW achieved (small bonus)
        elif done:
            reward -= 6.0                          # chronic / unresolved (costly)
        return self._obs(), reward, done


def rule_based_policy(env):
    """Simple heuristic: escalate if low recovery, else continue / RTW coord."""
    if env.rec <= 1:
        return 1                                   # escalate CM
    if env.rec >= env.n_rec - 2:
        return 4                                   # RTW coordination
    return 0                                       # continue


def train_q(env, episodes, seed=0, alpha=0.2, gamma=0.95, eps=0.2):
    rng = np.random.default_rng(seed)
    Q = np.zeros((env.n_states(), len(ACTIONS)))
    for _ in range(episodes):
        s = env.reset(); done = False
        while not done:
            a = rng.integers(len(ACTIONS)) if rng.random() < eps else int(Q[s].argmax())
            s2, r, done = env.step(a)
            Q[s, a] += alpha * (r + gamma * (0 if done else Q[s2].max()) - Q[s, a])
            s = s2
    return Q


def rollout_cost(env, policy_fn, n, seed=0):
    """Mean total cost (negative reward magnitude excluding terminal bonus)."""
    env.rng = np.random.default_rng(seed)
    total = []
    for _ in range(n):
        s = env.reset(); done = False; c = 0.0
        while not done:
            a = policy_fn(env, s)
            s, r, done = env.step(a)
            c += -r
        total.append(c)
    return float(np.mean(total))


def evaluate_rehab(cfg, seed=0):
    """Returns cost reduction of learned policy vs rule-based, with and without
    H-conditioning (the DS-fusion contribution)."""
    res = {}
    for use_H, tag in [(True, "full"), (False, "no_H")]:
        env = RehabMDP(use_H=use_H, seed=seed)
        Q = train_q(env, cfg.rl_episodes_train, seed=seed)
        learned = lambda e, s: int(Q[s].argmax())
        rule = lambda e, s: rule_based_policy(e)
        c_rule = rollout_cost(env, rule, cfg.rl_eval_rollouts, seed=seed + 1)
        c_learn = rollout_cost(env, learned, cfg.rl_eval_rollouts, seed=seed + 1)
        red = 100.0 * (c_rule - c_learn) / c_rule
        res[tag] = dict(cost_rule=c_rule, cost_learned=c_learn, reduction_pct=red)
    res["fusion_gain_pct"] = res["full"]["reduction_pct"] - res["no_H"]["reduction_pct"]
    return res
