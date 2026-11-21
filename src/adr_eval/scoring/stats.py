"""Agreement and paired statistics (no scipy dependency)."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np


def cohen_kappa(a: list[str], b: list[str]) -> float:
    if len(a) != len(b):
        raise ValueError("rating lists differ in length")
    if not a:
        raise ValueError("empty rating lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca.keys() & cb.keys()) / (n * n)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def paired_bootstrap_ci(
    x: list[float], y: list[float], n: int = 10_000, seed: int = 20261108, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Mean of y - x with a percentile bootstrap interval over paired resamples."""
    if len(x) != len(y):
        raise ValueError("x and y differ in length")
    if not x:
        raise ValueError("empty samples")
    d = np.asarray(y, dtype=float) - np.asarray(x, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(d), size=(n, len(d)))
    means = d[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(d.mean()), float(lo), float(hi)


def bootstrap_mean_ci(
    values: list[float], n: int = 10_000, seed: int = 20261108, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Mean with a percentile bootstrap interval (same rng and method as paired_bootstrap_ci)."""
    if not values:
        raise ValueError("empty sample")
    v = np.asarray(values, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(v), size=(n, len(v)))
    means = v[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(v.mean()), float(lo), float(hi)


def cluster_bootstrap_ratio_ci(
    nums: list[float], dens: list[float], n: int = 10_000, seed: int = 20261108,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """sum(nums) / sum(dens) with a percentile bootstrap interval resampling clusters (items).

    Each cluster i contributes numerator nums[i] and denominator dens[i]; every resample
    draws clusters with replacement and takes the ratio of the summed numerators to the
    summed denominators; every denominator must be positive. With every denominator 1 this
    is bootstrap_mean_ci, bit for bit (same rng construction and index draws).
    """
    if len(nums) != len(dens):
        raise ValueError("nums and dens differ in length")
    if not nums:
        raise ValueError("empty sample")
    num, den = np.asarray(nums, dtype=float), np.asarray(dens, dtype=float)
    if den.sum() == 0:
        raise ValueError("total denominator is zero")
    if (den <= 0).any():
        raise ValueError("every denominator must be positive (drop empty clusters first)")
    idx = np.random.default_rng(seed).integers(0, len(num), size=(n, len(num)))
    ratios = num[idx].sum(axis=1) / den[idx].sum(axis=1)
    lo, hi = np.percentile(ratios, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(num.sum() / den.sum()), float(lo), float(hi)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial (p=0.5) on the b + c discordant pairs."""
    total = b + c
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2**total)


def holm(pvals: dict[str, float]) -> dict[str, float]:
    m = len(pvals)
    out: dict[str, float] = {}
    running = 0.0
    for j, (key, p) in enumerate(sorted(pvals.items(), key=lambda kv: (kv[1], kv[0]))):
        running = max(running, (m - j) * p)
        out[key] = min(1.0, running)
    return out


def paired_ratio_diff_ci(
    num_a: list[float], den_a: list[float], num_b: list[float], den_b: list[float],
    n: int = 10_000, seed: int = 20261108, alpha: float = 0.05,
) -> tuple[float, float, float]:
    """sum(num_b)/sum(den_b) - sum(num_a)/sum(den_a) with a percentile bootstrap interval that
    resamples clusters (items or tasks) with replacement, the same draw for both sides (paired).

    Cluster i contributes (num_a[i], den_a[i]) and (num_b[i], den_b[i]). A resample whose summed
    denominator is zero on either side has no ratio and is left out of the percentiles; each
    side's total denominator must be positive. The rng construction and index draws are those
    of `cluster_bootstrap_ratio_ci`, so with every num_a zero the result equals
    `cluster_bootstrap_ratio_ci(num_b, den_b)` bit for bit.
    """
    lengths = {len(num_a), len(den_a), len(num_b), len(den_b)}
    if len(lengths) != 1:
        raise ValueError("num_a, den_a, num_b and den_b differ in length")
    if not num_a:
        raise ValueError("empty sample")
    na, da = np.asarray(num_a, dtype=float), np.asarray(den_a, dtype=float)
    nb, db = np.asarray(num_b, dtype=float), np.asarray(den_b, dtype=float)
    if da.sum() <= 0 or db.sum() <= 0:
        raise ValueError("total denominator is zero")
    if (da < 0).any() or (db < 0).any():
        raise ValueError("denominators must not be negative")
    idx = np.random.default_rng(seed).integers(0, len(na), size=(n, len(na)))
    sa, sb = da[idx].sum(axis=1), db[idx].sum(axis=1)
    keep = (sa > 0) & (sb > 0)
    diffs = nb[idx].sum(axis=1)[keep] / sb[keep] - na[idx].sum(axis=1)[keep] / sa[keep]
    lo, hi = np.percentile(diffs, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(nb.sum() / db.sum() - na.sum() / da.sum()), float(lo), float(hi)
