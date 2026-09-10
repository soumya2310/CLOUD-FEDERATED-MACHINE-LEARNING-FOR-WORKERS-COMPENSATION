"""Federated learning domain: FedProx with Gaussian differential privacy.

A logistic-regression RTW classifier is trained across non-IID clients
(partitioned by employer sector). We record REAL test AUC per round, the gap
to a centralized model, and compute the (epsilon, delta) budget by Renyi-DP
composition. All quantities come from actual training runs.
"""
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

from .simulate import rolling_features


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _grad(w, X, y, mu=0.0, w_global=None):
    p = _sigmoid(X @ w)
    g = X.T @ (p - y) / len(y)
    if mu > 0 and w_global is not None:
        g = g + mu * (w - w_global)
    return g


def _local_train(w_global, X, y, steps=5, lr=0.3, mu=0.0):
    w = w_global.copy()
    for _ in range(steps):
        w -= lr * _grad(w, X, y, mu, w_global)
    return w - w_global                      # update (delta)


def _auc(w, X, y):
    try:
        return roc_auc_score(y, _sigmoid(X @ w))
    except ValueError:
        return float("nan")


def dp_epsilon(sigma, T, delta):
    """(eps, delta)-DP from T-round Gaussian mechanism via RDP composition:
        eps(delta) = min_alpha [ T*alpha/(2 sigma^2) + log(1/delta)/(alpha-1) ]."""
    alphas = np.linspace(1.1, 64, 400)
    eps = T * alphas / (2 * sigma ** 2) + np.log(1 / delta) / (alphas - 1)
    return float(eps.min())


def run_federated(df, cfg, seed=0):
    rng = np.random.default_rng(seed)
    X, _ = rolling_features(df)
    X = StandardScaler().fit_transform(X)
    X = np.column_stack([X, np.ones(len(X))])         # bias term
    time = df["time"].to_numpy(); cause = df["cause"].to_numpy()
    y = ((time <= cfg.brier_horizon) & (cause == 0)).astype(float)
    sector = df["sector_idx"].to_numpy()

    # split test set
    n = len(X); idx = rng.permutation(n)
    n_te = int(cfg.test_frac * n)
    te, tr = idx[:n_te], idx[n_te:]
    Xte, yte = X[te], y[te]

    # centralized upper bound
    wc = np.zeros(X.shape[1])
    for _ in range(300):
        wc -= 0.3 * _grad(wc, X[tr], y[tr])
    auc_central = _auc(wc, Xte, yte)

    # partition train across orgs by sector (non-IID)
    orgs = []
    tr_sector = sector[tr]
    for k in range(cfg.n_orgs):
        # each org drawn predominantly from one sector -> non-IID
        s = k % len(cfg.sectors)
        pool = tr[(tr_sector == s)]
        if len(pool) < 20:
            pool = tr
        take = rng.choice(pool, size=max(30, len(pool) // (cfg.n_orgs // len(cfg.sectors) + 1)), replace=True)
        orgs.append(take)

    def federated(mu, sigma):
        w = np.zeros(X.shape[1])
        curve = []
        for t in range(cfg.fed_rounds):
            deltas = []
            for take in orgs:
                d = _local_train(w, X[take], y[take], steps=5, lr=0.3, mu=mu)
                # clip + Gaussian DP noise
                norm = np.linalg.norm(d)
                d = d / max(1.0, norm / cfg.dp_clip)
                if sigma > 0:
                    d = d + rng.normal(0, sigma * cfg.dp_clip, size=d.shape)
                deltas.append(d)
            w = w + np.mean(deltas, axis=0)
            curve.append(_auc(w, Xte, yte))
        return np.array(curve)

    curve_fedprox_dp = federated(cfg.fedprox_mu, cfg.dp_noise_multiplier)
    curve_fedavg = federated(0.0, 0.0)
    curve_fedprox = federated(cfg.fedprox_mu, 0.0)

    eps = dp_epsilon(cfg.dp_noise_multiplier, cfg.fed_rounds, cfg.dp_delta)
    final = curve_fedprox_dp[-1]
    gap_pct = 100.0 * (auc_central - final) / auc_central
    # rounds to within 3% of centralized
    within = np.where(curve_fedprox_dp >= 0.97 * auc_central)[0]
    rounds_to_converge = int(within[0] + 1) if len(within) else cfg.fed_rounds
    return {
        "auc_central": float(auc_central),
        "final_auc_dp": float(final),
        "gap_pct": float(gap_pct),
        "rounds_to_converge": rounds_to_converge,
        "epsilon": eps,
        "delta": cfg.dp_delta,
        "curve_fedprox_dp": curve_fedprox_dp.tolist(),
        "curve_fedavg": curve_fedavg.tolist(),
        "curve_fedprox": curve_fedprox.tolist(),
    }
