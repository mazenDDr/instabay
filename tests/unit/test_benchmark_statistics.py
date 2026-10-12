"""FR-14: independent hand-calculated agreement, quantile and paired interval examples."""

from statistics import mean

import pytest

from instabay.benchmarks.statistics import (
    bootstrap,
    krippendorff_alpha,
    paired_bootstrap,
    percentile,
    quadratic_kappa,
    relative_change,
    spearman,
)


def test_percentiles_and_constant_bootstrap() -> None:
    assert percentile([10, 0], 0.95) == 9.5
    estimate = bootstrap([4.6] * 21, resamples=50)
    assert estimate.mean == estimate.low == estimate.high == pytest.approx(4.6)
    assert estimate.n == 21
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_pairing_preserves_constant_difference_and_ratio_of_means() -> None:
    before = [1, 2, 10]
    after = [2, 3, 11]
    difference = paired_bootstrap(after, before, lambda a, b: mean(a) - mean(b), resamples=100)
    assert (difference.mean, difference.low, difference.high) == pytest.approx((1, 1, 1))
    ratio = paired_bootstrap(after, before, relative_change, resamples=100)
    assert ratio.mean == pytest.approx(3 / 13)
    assert ratio == paired_bootstrap(after, before, relative_change, resamples=100)
    with pytest.raises(ValueError):
        paired_bootstrap([1], [1, 2], relative_change)
    with pytest.raises(ValueError):
        relative_change([1], [0])


def test_quadratic_kappa_known_cases() -> None:
    assert quadratic_kappa([1, 3, 5], [1, 3, 5]) == 1
    # Opposite labels: observed squared distance 16, independent expectation 8.
    assert quadratic_kappa([1, 5], [5, 1]) == -1
    assert quadratic_kappa([3, 3], [3, 3]) is None
    with pytest.raises(ValueError):
        quadratic_kappa([0], [1])


def test_interval_alpha_hand_calculated_and_missing_raters() -> None:
    # Do=1, De=10/3 for [1,2],[3,4], hence alpha=0.7.
    assert krippendorff_alpha([[1, 2], [3, 4]]) == pytest.approx(0.7)
    assert krippendorff_alpha([[1, 1], [5, 5]]) == 1
    assert krippendorff_alpha([[1, 5], [5, 1]]) == pytest.approx(-0.5)
    assert krippendorff_alpha([[1], [3]]) is None
    assert krippendorff_alpha([[3, 3], [3, 3]]) is None
    assert krippendorff_alpha([[1, 2], [3, 4], [5]]) == pytest.approx(0.7)


def test_tied_spearman_and_constant_data() -> None:
    assert spearman([1, 1, 3], [5, 5, 2]) == pytest.approx(-1)
    assert spearman([1, 2, 3], [4, 4, 4]) is None
    assert spearman([1], [5]) is None
