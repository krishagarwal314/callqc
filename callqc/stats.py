"""Bootstrap confidence intervals and significance tests, so a lift is never claimed from noise."""
from __future__ import annotations

import numpy as np
from scipy.stats import fisher_exact


def bootstrap_ci(values, n_boot: int = 4000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    x = np.asarray(values, dtype=float)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), (n_boot, len(x)))].mean(axis=1)
    return float(x.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def bootstrap_diff_ci(a, b, n_boot: int = 4000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    """CI for mean(b) - mean(a), resampling each group independently."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    rng = np.random.default_rng(seed)
    da = a[rng.integers(0, len(a), (n_boot, len(a)))].mean(axis=1)
    db = b[rng.integers(0, len(b), (n_boot, len(b)))].mean(axis=1)
    d = db - da
    return float(b.mean() - a.mean()), float(np.quantile(d, alpha / 2)), float(np.quantile(d, 1 - alpha / 2))


def fisher_p(a_success: int, a_n: int, b_success: int, b_n: int) -> float:
    return float(fisher_exact([[a_success, a_n - a_success], [b_success, b_n - b_success]])[1])


def permutation_p(a, b, n_perm: int = 5000, seed: int = 0) -> float:
    """Two-sided permutation test on the difference in means."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    observed = abs(b.mean() - a.mean())
    pooled = np.concatenate([a, b])
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        hits += abs(pooled[len(a):].mean() - pooled[:len(a)].mean()) >= observed
    return (hits + 1) / (n_perm + 1)


def holm(pvalues: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted
