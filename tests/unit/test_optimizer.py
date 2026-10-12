"""FR-13: exact fractional updates and planner properties under sampled beliefs."""

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from instabay.core.learning import BetaPosterior
from instabay.core.optimizer import ThompsonOptimizer, factor_levels, update_posterior
from instabay.core.planner import plan_week
from tests.support import demo_brand


def test_worked_update_matches_spec() -> None:
    belief = BetaPosterior(factor="pillar", level="underwater", alpha=4.2, beta=56.8)
    updated = update_posterior(belief, 0.056)
    assert updated.alpha == pytest.approx(5.32)
    assert updated.beta == pytest.approx(75.68)
    assert belief.alpha == 4.2  # Immutable input.


@pytest.mark.parametrize("rate", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_rewards_fail(rate: float) -> None:
    with pytest.raises(ValueError):
        update_posterior(BetaPosterior(factor="format", level="photo"), rate)


@given(
    seed=st.integers(min_value=0, max_value=2**32),
    parameters=st.lists(
        st.tuples(
            st.floats(min_value=0.1, max_value=100, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0.1, max_value=100, allow_nan=False, allow_infinity=False),
        ),
        min_size=15,
        max_size=15,
    ),
)
@settings(max_examples=100, database=None)
def test_sampled_plans_always_respect_brand_limits(
    seed: int, parameters: list[tuple[float, float]]
) -> None:
    brand = demo_brand()
    levels = [(factor, level) for factor, names in factor_levels(brand).items() for level in names]
    beliefs = [
        BetaPosterior(factor=factor, level=level, alpha=alpha, beta=beta)
        for (factor, level), (alpha, beta) in zip(levels, parameters, strict=True)
    ]
    optimizer = ThompsonOptimizer(seed)
    scores = optimizer.preferences(brand, beliefs, "week1")
    assert scores == optimizer.preferences(brand, list(reversed(beliefs)), "week1")
    plan = plan_week(brand, "a" * 64, "property", date(2026, 10, 12), scores)
    assert len(plan) == brand.cadence.posts_per_week
    for pillar in brand.pillars:
        share = sum(slot.arm.pillar == pillar.id for slot in plan) / len(plan)
        assert pillar.min_share <= share <= pillar.max_share
    assert sum(slot.arm.format == "reel" for slot in plan) >= brand.cadence.min_reels
    assert sum(slot.explore for slot in plan) >= 1
    for slot in plan:
        assert str(slot.scheduled_at.tzinfo) == "Africa/Cairo"
        assert not 1 <= slot.scheduled_at.hour < 7
        assert (
            slot.scheduled_at.strftime("%H:%M") == brand.cadence.windows_cairo[slot.arm.time_bucket]
        )
    assert plan == plan_week(brand, "a" * 64, "property", date(2026, 10, 12), scores)


def test_beliefs_change_next_preferences() -> None:
    optimizer = ThompsonOptimizer(7)
    prior = optimizer.preferences(demo_brand(), [], "next")
    concentrated = BetaPosterior(factor="format", level="photo", alpha=10000, beta=1)
    posterior = optimizer.preferences(demo_brand(), [concentrated], "next")
    assert posterior.format["photo"] > 0.99
    assert posterior.format["photo"] != prior.format["photo"]
    assert posterior.hook_style == prior.hook_style


def test_duplicate_posterior_is_rejected() -> None:
    row = BetaPosterior(factor="format", level="photo")
    with pytest.raises(ValueError, match="Duplicate"):
        ThompsonOptimizer(7).preferences(demo_brand(), [row, row], "next")
