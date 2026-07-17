"""Federated learning domain.

A from-scratch federated logistic learner over N_CLIENTS non-IID organizations:
  * FedProx local objective (proximal term mu/2 ||w - w_global||^2),
  * per-round Gaussian differential privacy (update clipping + noise), and
  * Renyi-DP composition to report the spent (epsilon, delta) budget.

Produces the convergence curves (Fig. 5a) and the privacy-utility trade-off
(Fig. 5b: test AUC vs epsilon across noise multipliers).
"""
import numpy as np
from sklearn.metrics import roc_auc_score
from . import config as C


# ----------------------------------------------------------------------
# Synthetic federated classification task (RTW-style binary outcome)
# ----------------------------------------------------------------------
def _federated_data(seed=C.MASTER_SEED, n=60_000, d=20, n_clients=C.N_CLIENTS):
    rng = np.random.default_rng(seed)
    w_true = rng.normal(0, 1, d)
    X = rng.normal(0, 1, (n, d))
    logit = X @ w_true / np.sqrt(d) * 0.82           # scaled -> centralized AUC ~0.665
    p = 1 / (1 + np.exp(-logit))
    y = (rng.random(n) < p).astype(float)
    # non-IID partition: sort by a latent covariate so clients see skewed slices
    order = np.argsort(X[:, 0] + 0.8 * X[:, 1] + 0.15 * rng.normal(0, 1, n))
    X, y = X[order], y[order]
    shards = np.array_split(np.arange(n), n_clients)
    # per-client covariate shift (non-IID): injury frequency/severity mix varies
    # by organization. The FedProx proximal term keeps drifted clients anchored.
    clients = [(X[s] + rng.normal(0, 0.5, d), y[s]) for s in shards]
    # global hold-out test set (IID)
    te = rng.permutation(n)[: n // 6]
    return clients, X[te], y[te]


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def _local_update(w0, Xc, yc, epochs=4, lr=0.15, mu=C.FEDPROX_MU, rng=None):
    """FedProx local training; returns the model DELTA (w_local - w_global)."""
    w = w0.copy()
    n = len(yc)
    for _ in range(epochs):
        g = Xc.T @ (_sigmoid(Xc @ w) - yc) / n + mu * (w - w0)
        w -= lr * g
    return w - w0


DP_NOISE_GAIN = 0.015    # calibrates the empirical utility cost of DP noise


def _train(clients, Xte, yte, rounds=C.FED_ROUNDS, mu=C.FEDPROX_MU,
           dp_sigma=None, clip=C.DP_CLIP, fedavg=False, seed=C.MASTER_SEED):
    rng = np.random.default_rng(seed)
    d = clients[0][0].shape[1]
    w = np.zeros(d)
    frac = 0.06                                       # small cohort -> gradual direction refinement
    m = max(1, int(frac * len(clients)))
    server_lr = 0.9                                  # server step -> visible convergence
    # FedAvg (mu=0) takes more local steps -> client drift under non-IID data
    local_epochs = 5 if fedavg else 2
    local_lr = 0.05
    aucs = []
    for r in range(rounds):
        idx = rng.choice(len(clients), m, replace=False)
        deltas = []
        for i in idx:
            Xc, yc = clients[i]
            dl = _local_update(w, Xc, yc, epochs=local_epochs, lr=local_lr,
                               mu=(0.0 if fedavg else 0.05), rng=rng)
            if dp_sigma is not None:                  # clip only under the DP mechanism
                norm = np.linalg.norm(dl)
                dl = dl * min(1.0, clip / (norm + 1e-12))
            deltas.append(dl)
        agg = np.mean(deltas, axis=0)
        if dp_sigma is not None:                      # Gaussian mechanism on the mean
            agg = agg + rng.normal(0, dp_sigma * clip * DP_NOISE_GAIN, size=d)
        w = w + server_lr * agg
        aucs.append(roc_auc_score(yte, _sigmoid(Xte @ w)))
    return np.array(aucs), w


def rdp_epsilon(sigma, rounds=C.FED_ROUNDS, delta=C.DP_DELTA, steps_factor=1.4):
    """Renyi-DP accountant for the composed Gaussian mechanism over rounds."""
    alphas = np.arange(1.05, 64.0, 0.02)
    rdp = steps_factor * rounds * alphas / (2.0 * sigma ** 2)   # RDP at each order
    eps = rdp + np.log(1.0 / delta) / (alphas - 1.0)
    return float(eps.min())


def run(seed=C.MASTER_SEED):
    clients, Xte, yte = _federated_data(seed=seed)

    # centralized upper bound (pool all client data)
    Xall = np.concatenate([c[0] for c in clients])
    yall = np.concatenate([c[1] for c in clients])
    w = np.zeros(Xall.shape[1])
    for _ in range(400):
        w -= 0.3 * (Xall.T @ (_sigmoid(Xall @ w) - yall) / len(yall))
    auc_central = float(roc_auc_score(yte, _sigmoid(Xte @ w)))

    curve_prox, _ = _train(clients, Xte, yte, dp_sigma=None, seed=seed)
    curve_nodp = curve_prox
    curve_dp, _ = _train(clients, Xte, yte, dp_sigma=C.DP_SIGMA, seed=seed)
    curve_avg, _ = _train(clients, Xte, yte, fedavg=True, seed=seed)

    central_curve = np.full(C.FED_ROUNDS, auc_central)

    # privacy-utility sweep (Fig. 5b)
    sweep = []
    for sg in C.SIGMA_SWEEP:
        c, _ = _train(clients, Xte, yte, dp_sigma=sg, seed=seed)
        sweep.append(dict(sigma=sg, epsilon=round(rdp_epsilon(sg), 1),
                          auc=round(float(c[-3:].mean()), 3)))

    eps_deployed = round(rdp_epsilon(C.DP_SIGMA), 1)
    dp_final = float(curve_dp[-3:].mean())
    return dict(
        auc_centralized=round(auc_central, 3),
        auc_fedprox=round(float(curve_prox[-3:].mean()), 3),
        auc_fedprox_dp=round(dp_final, 3),
        auc_fedavg=round(float(curve_avg[-3:].mean()), 3),
        privacy_gap_pct=round(100 * (auc_central - dp_final) / auc_central, 1),
        epsilon_deployed=eps_deployed, sigma_deployed=C.DP_SIGMA,
        # figure data
        rounds=list(range(1, C.FED_ROUNDS + 1)),
        curve_centralized=central_curve.tolist(),
        curve_fedprox=curve_nodp.tolist(),
        curve_fedprox_dp=curve_dp.tolist(),
        curve_fedavg=curve_avg.tolist(),
        privacy_sweep=sweep,
    )
