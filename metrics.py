"""Shared metric helpers: bootstrap confidence intervals and calibration error."""
import numpy as np


def bootstrap_ci(values, stat=np.mean, n_boot=2000, alpha=0.05, seed=0):
    rng = np.random.default_rng(seed)
    values = np.asarray(values)
    boots = [stat(values[rng.integers(0, len(values), len(values))]) for _ in range(n_boot)]
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def expected_calibration_error(y, p, bins=10):
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -1e9, 1e9
    ece = 0.0
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1])
        if m.sum():
            ece += m.mean() * abs(np.asarray(y)[m].mean() - np.asarray(p)[m].mean())
    return float(ece)
