"""FR-14: seed-cluster bootstrap and agreement calculations, without network libraries."""

import math
import random
from collections import Counter
from collections.abc import Callable, Sequence
from statistics import mean

from pydantic import Field

from instabay.core.schemas import Boundary


class Estimate(Boundary):
    """FR-14: percentile 95% interval; n counts independent resampling units."""

    mean: float
    low: float
    high: float
    n: int = Field(ge=1)


def percentile(values: Sequence[float], fraction: float) -> float:
    """FR-14: linearly interpolated quantile, including p50/p95 latency."""
    if not values or not 0 <= fraction <= 1 or any(not math.isfinite(v) for v in values):
        raise ValueError("Quantiles need finite data and a fraction in [0,1]")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap(values: Sequence[float], seed: int = 42, resamples: int = 2000) -> Estimate:
    """FR-14: a mean interval over posts or world seeds, never over correlated posts as seeds."""
    return paired_bootstrap(values, values, lambda a, b: mean(a), seed, resamples)


def paired_bootstrap(
    left: Sequence[float],
    right: Sequence[float],
    statistic: Callable[[Sequence[float], Sequence[float]], float],
    seed: int = 42,
    resamples: int = 2000,
) -> Estimate:
    """FR-14: resample paired world indices; retain the full within-world history."""
    if not left or len(left) != len(right) or resamples < 1:
        raise ValueError("Bootstrap requires equal nonempty paired data and positive resamples")
    if any(not math.isfinite(value) for value in (*left, *right)):
        raise ValueError("Bootstrap data must be finite")
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        indexes = [rng.randrange(len(left)) for _ in left]
        draws.append(statistic([left[i] for i in indexes], [right[i] for i in indexes]))
    return Estimate(
        mean=statistic(left, right),
        low=percentile(draws, 0.025),
        high=percentile(draws, 0.975),
        n=len(left),
    )


def relative_change(left: Sequence[float], right: Sequence[float]) -> float:
    """FR-14: relative change of policy means, not a mean of unstable seed-level ratios."""
    baseline = mean(right)
    if baseline <= 0:
        raise ValueError("Relative uplift needs a positive baseline")
    return mean(left) / baseline - 1


def quadratic_kappa(left: Sequence[int], right: Sequence[int]) -> float | None:
    """FR-14: quadratic weighted Cohen's kappa for the fixed ordinal 1-5 rubric."""
    if not left or len(left) != len(right) or any(v not in range(1, 6) for v in (*left, *right)):
        raise ValueError("Kappa requires paired ordinal labels in 1..5")
    count = len(left)
    lcounts, rcounts = Counter(left), Counter(right)
    observed = sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) / count
    expected = (
        sum(lcounts[a] * rcounts[b] * (a - b) ** 2 for a in range(1, 6) for b in range(1, 6))
        / count**2
    )
    return 1 - observed / expected if expected else None


def krippendorff_alpha(items: Sequence[Sequence[float]]) -> float | None:
    """FR-14: interval alpha over quality means; missing/single-rater items are excluded."""
    usable = [list(item) for item in items if len(item) >= 2]
    if not usable:
        return None
    flattened = [score for item in usable for score in item]
    if any(not math.isfinite(score) or not 1 <= score <= 5 for score in flattened):
        raise ValueError("Alpha scores must be finite in [1,5]")
    total = len(flattened)
    observed = (
        sum(sum((a - b) ** 2 for a in item for b in item) / (len(item) - 1) for item in usable)
        / total
    )
    # Sum of all ordered squared distances, using an O(n) identity.
    expected = (
        2 * (total * sum(x * x for x in flattened) - sum(flattened) ** 2) / (total * (total - 1))
    )
    return 1 - observed / expected if expected > 0 else None


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    """FR-14: tied ranks use average rank; constant scores have undefined correlation."""
    if len(left) != len(right) or len(left) < 2:
        return None
    if any(not math.isfinite(value) for value in (*left, *right)):
        raise ValueError("Correlation needs finite scores")

    def ranks(values: Sequence[float]) -> list[float]:
        positions: dict[float, list[int]] = {}
        for index, value in enumerate(sorted(values), 1):
            positions.setdefault(value, []).append(index)
        return [mean(positions[value]) for value in values]

    x, y = ranks(left), ranks(right)
    xm, ym = mean(x), mean(y)
    numerator = sum((a - xm) * (b - ym) for a, b in zip(x, y, strict=True))
    denominator = math.sqrt(sum((a - xm) ** 2 for a in x) * sum((b - ym) ** 2 for b in y))
    return numerator / denominator if denominator else None
