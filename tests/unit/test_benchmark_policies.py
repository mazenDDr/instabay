"""FR-14: constrained oracle bound, uniform planning, leakage guards and deterministic pairing."""

import math
from datetime import date

import pytest

from instabay.benchmarks.policies import ConstrainedOracle, evaluate_seed, uniform_arms
from instabay.core.optimizer import ThompsonOptimizer
from instabay.core.planner import plan_week
from instabay.core.schemas import Arm
from sim.world import AudienceWorld, SimArm, WorldConfig
from tests.support import demo_brand


def assert_limits(arms: list[Arm]) -> None:
    brand = demo_brand()
    assert len(arms) == 7
    for pillar in brand.pillars:
        share = sum(arm.pillar == pillar.id for arm in arms) / 7
        assert pillar.min_share <= share <= pillar.max_share
    assert sum(arm.format == "reel" for arm in arms) >= 1
    assert arms[0].hook_style != arms[1].hook_style
    assert arms[0].time_bucket != arms[1].time_bucket


def test_oracle_bounds_random_and_production_plans() -> None:
    brand = demo_brand()
    for seed in range(4):
        oracle = ConstrainedOracle(AudienceWorld(seed), brand)
        optimum = list(oracle.optimal())
        assert_limits(optimum)
        bound = oracle.reward(optimum)
        for week in range(1, 11):
            random_plan = uniform_arms(brand, seed, week)
            assert_limits(random_plan)
            assert bound >= oracle.reward(random_plan) - 1e-12
            sampled = plan_week(
                brand,
                "a" * 64,
                "property",
                date(2026, 10, 12),
                ThompsonOptimizer(seed).preferences(brand, [], f"w{week:02d}"),
            )
            assert bound >= oracle.reward([slot.arm for slot in sampled]) - 1e-12


class FormatWorld(AudienceWorld):
    def _logit(self, arm: SimArm) -> float:
        return {"photo": -1.0, "carousel": -10.0, "reel": -5.0}[arm.format]


def test_oracle_exact_minimum_reel_tradeoff() -> None:
    oracle = ConstrainedOracle(FormatWorld(0, WorldConfig(noise_sigma=0)), demo_brand())
    plan = list(oracle.optimal())
    assert sum(arm.format == "photo" for arm in plan) == 6
    assert sum(arm.format == "reel" for arm in plan) == 1
    assert oracle.reward(plan) == pytest.approx(6 / (1 + math.exp(1)) + 1 / (1 + math.exp(5)))


@pytest.mark.determinism
def test_seed_replay_fixed_baseline_and_leakage_guard() -> None:
    results, evidence = evaluate_seed(demo_brand(), 3, weeks=3)
    assert (results, evidence) == evaluate_seed(demo_brand(), 3, weeks=3)
    by_policy = {(row.policy, row.week): row for row in evidence}
    assert by_policy[("fixed", 1)].planned == by_policy[("thompson", 1)].planned
    assert by_policy[("fixed", 1)].rates == by_policy[("thompson", 1)].rates
    assert all(row.regret >= -1e-12 for row in evidence)
    for row in evidence:
        assert_limits(row.executed)
        if row.policy == "fixed":
            assert row.planned == by_policy[("fixed", 1)].planned
        if row.policy == "oracle":
            assert row.regret == 0
        if row.policy == "leak_guarded":
            assert row.learned == (0 if row.leaked else 7)
        if row.policy == "leak_unguarded":
            assert row.learned == 7
    assert len(results) == 6
