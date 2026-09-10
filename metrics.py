"""Evaluation utilities: all statistics here are computed from real arrays."""
import numpy as np
from scipy import stats


def bootstrap_ci(values, statfn, reps=1000, seed=0, alpha=0.05):
    """Bias-corrected-ish percentile bootstrap CI for a statistic of paired arrays.

    `values` is a tuple of equal-length arrays passed to statfn(*resampled).
    Returns (point, lo, hi).
    """
    rng = np.random.default_rng(seed)
    n = len(values[0])
    point = statfn(*values)
    boot = np.empty(reps)
    idx_all = np.arange(n)
    for b in range(reps):
        idx = rng.choice(idx_all, size=n, replace=True)
        boot[b] = statfn(*[v[idx] for v in values])
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(point), float(lo), float(hi)


def expected_calibration_error(y_true, p_pred, n_bins=10):
    """Equal-mass (quantile) binned ECE."""
    y_true = np.asarray(y_true, float)
    p_pred = np.asarray(p_pred, float)
    order = np.argsort(p_pred)
    y_true, p_pred = y_true[order], p_pred[order]
    bins = np.array_split(np.arange(len(p_pred)), n_bins)
    ece = 0.0
    n = len(p_pred)
    for b in bins:
        if len(b) == 0:
            continue
        conf = p_pred[b].mean()
        acc = y_true[b].mean()
        ece += (len(b) / n) * abs(acc - conf)
    return float(ece)


def ks_fidelity(sample, target_mean=None, target_sd=None, ref_sample=None):
    """Two-sample KS p-value of `sample` against a reference.

    If ref_sample given, use it; else build a normal reference from target
    mean/sd. Returns p-value (>0.05 => fail to reject equality).
    """
    if ref_sample is None:
        rng = np.random.default_rng(0)
        sd = target_sd if target_sd is not None else max(1e-6, 0.25 * abs(target_mean))
        ref_sample = rng.normal(target_mean, sd, size=len(sample))
    return float(stats.ks_2samp(sample, ref_sample).pvalue)


def wilcoxon_p(a, b):
    """Paired Wilcoxon signed-rank p-value between two fold-metric vectors."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or np.allclose(a, b):
        return float("nan")
    try:
        return float(stats.wilcoxon(a, b).pvalue)
    except ValueError:
        return float("nan")


def auc(y_true, score):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y_true, score))


def f1_prec_rec(y_true, y_pred):
    from sklearn.metrics import precision_recall_fscore_support
    p, r, f, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0)
    return float(f), float(p), float(r)
