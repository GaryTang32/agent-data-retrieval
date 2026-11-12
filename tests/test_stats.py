import pytest

from adr_eval.scoring.stats import (
    bootstrap_mean_ci,
    cluster_bootstrap_ratio_ci,
    cohen_kappa,
    holm,
    mcnemar_exact,
    paired_bootstrap_ci,
)


def test_kappa_known_value():
    assert cohen_kappa(list("ccwwc"), list("ccwcc")) == pytest.approx(0.5454545, rel=1e-6)


def test_kappa_constant_equal_is_one():
    assert cohen_kappa(["a", "a"], ["a", "a"]) == 1.0


def test_kappa_errors():
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"])
    with pytest.raises(ValueError):
        cohen_kappa([], [])


def test_bootstrap_reproducible_and_brackets_mean():
    x, y = [0, 0, 1, 1] * 25, [1, 0, 1, 1] * 25
    r1, r2 = paired_bootstrap_ci(x, y), paired_bootstrap_ci(x, y)
    assert r1 == r2 and r1[1] <= r1[0] <= r1[2] and r1[0] == pytest.approx(0.25)


def test_bootstrap_errors():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        paired_bootstrap_ci([], [])


def test_mcnemar_values():
    assert mcnemar_exact(0, 0) == 1.0 and mcnemar_exact(10, 0) == pytest.approx(2 * 0.5 ** 10)
    assert mcnemar_exact(5, 5) == 1.0


def test_holm_adjusts_monotonically():
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == pytest.approx(
        {"a": 0.03, "b": 0.06, "c": 0.06}
    )


def test_holm_caps_at_one():
    assert holm({"a": 0.6, "b": 0.7}) == pytest.approx({"a": 1.0, "b": 1.0})


def test_bootstrap_mean_ci_matches_paired_against_zero_and_brackets_mean():
    x = [1.0, -3.0, 0.0, -3.0, 1.0, 1.0]
    r = bootstrap_mean_ci(x)
    assert r == bootstrap_mean_ci(x)  # fixed seed
    assert r == paired_bootstrap_ci([0.0] * len(x), x)  # same rng and percentile method
    assert r[1] <= r[0] <= r[2] and r[0] == pytest.approx(-0.5)
    assert bootstrap_mean_ci([2.0, 2.0, 2.0]) == (2.0, 2.0, 2.0)


def test_bootstrap_mean_ci_empty_raises():
    with pytest.raises(ValueError):
        bootstrap_mean_ci([])


def test_cluster_ratio_ci_equals_bootstrap_mean_ci_when_every_denominator_is_one():
    x = [1.0, -3.0, 0.0, -3.0, 1.0, 1.0, 0.0]
    assert cluster_bootstrap_ratio_ci(x, [1.0] * len(x)) == bootstrap_mean_ci(x)  # bit-identical
    acc = [1.0, 0.0, 0.0, 1.0, 1.0]
    assert cluster_bootstrap_ratio_ci(acc, [1] * 5) == bootstrap_mean_ci(acc)


def test_cluster_ratio_ci_reproducible_and_brackets_full_sample_ratio():
    nums, dens = [3.0, 0.0, 1.0, 2.0, 5.0], [3.0, 2.0, 4.0, 2.0, 5.0]
    r = cluster_bootstrap_ratio_ci(nums, dens)
    assert r == cluster_bootstrap_ratio_ci(nums, dens)  # fixed seed
    assert r[0] == pytest.approx(11 / 16)  # sum(num) / sum(den), not the mean of item ratios
    assert r[1] <= r[0] <= r[2] and r[1] < r[2]


def test_cluster_ratio_ci_errors():
    with pytest.raises(ValueError):
        cluster_bootstrap_ratio_ci([], [])
    with pytest.raises(ValueError):
        cluster_bootstrap_ratio_ci([0.0, 0.0], [0.0, 0.0])
    with pytest.raises(ValueError):
        cluster_bootstrap_ratio_ci([1.0, 0.0], [1.0, 0.0])  # callers drop empty clusters
    with pytest.raises(ValueError):
        cluster_bootstrap_ratio_ci([1.0], [1.0, 1.0])


def test_cluster_ratio_ci_is_wider_than_treating_rows_as_independent():
    # 4 items x 5 repeats: two items always right, two always wrong. Resampling items gives
    # ratios k/4 with P(all four the same) = 1/16 per side, so the 95% interval is [0, 1];
    # resampling the 20 rows as if independent gives a much narrower interval around 0.5.
    mean, lo, hi = cluster_bootstrap_ratio_ci([5.0, 5.0, 0.0, 0.0], [5.0] * 4)
    assert (mean, lo, hi) == (0.5, 0.0, 1.0)
    row_mean, row_lo, row_hi = bootstrap_mean_ci([1.0] * 10 + [0.0] * 10)
    assert row_mean == 0.5 and 0.0 < row_lo < row_hi < 1.0
    assert hi - lo > row_hi - row_lo
