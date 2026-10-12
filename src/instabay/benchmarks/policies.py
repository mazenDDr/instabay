"""FR-14: predeclared policy comparison against the unchanged Phase 3 audience."""

import hashlib
import math
import random
from datetime import date, datetime, time, timedelta
from itertools import product
from statistics import mean
from typing import Literal

from pydantic import Field

from instabay.benchmarks.statistics import Estimate, bootstrap, paired_bootstrap, relative_change
from instabay.core.learning import BetaPosterior
from instabay.core.optimizer import ThompsonOptimizer, arm_levels, update_posterior
from instabay.core.planner import plan_week
from instabay.core.schemas import Arm, Boundary, BrandConstitution, Slot, canonical_hash
from sim.world import AudienceWorld, SimArm

Policy = Literal["fixed", "uniform", "thompson", "oracle", "leak_unguarded", "leak_guarded"]
POLICIES: tuple[Policy, ...] = (
    "fixed",
    "uniform",
    "thompson",
    "oracle",
    "leak_unguarded",
    "leak_guarded",
)


class PolicyWeek(Boundary):
    """FR-14: incremental per-seed/week evidence with planned and executed arms."""

    seed: int
    policy: Policy
    week: int = Field(ge=1)
    rates: list[float]
    reach: int = Field(ge=0)
    engagements: int = Field(ge=0)
    planned: list[Arm]
    executed: list[Arm]
    leaked: int = Field(ge=0)
    learned: int = Field(ge=0)
    expected_reward: float
    oracle_reward: float
    regret: float


class SeedResult(Boundary):
    """FR-14: one independent bootstrap unit contains 12 x 7 observations."""

    seed: int
    policy: Policy
    late_rate: float = Field(ge=0, le=1)
    cumulative_regret: float
    leaked: int
    learned: int


class PolicySummary(Boundary):
    """FR-14: intervals over world seeds; regret units are expected rate summed over posts."""

    late_engagement_rate: Estimate
    cumulative_regret: Estimate
    leaked_posts: int
    learned_posts: int


class OptimizationMetric(Boundary):
    """FR-14: synthetic policy outcomes and explicitly synthetic hook-drift ablation."""

    weeks: int
    posts_per_week: int
    seeds: list[int]
    evaluation_weeks: list[int]
    summaries: dict[Policy, PolicySummary]
    uplift: Estimate
    leakage_guard_regret_difference: Estimate
    seed_results: list[SeedResult]
    assumptions: list[str]


def keyed_rng(seed: int, key: str) -> random.Random:
    digest = hashlib.sha256(f"bench-v1:{seed}:{key}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


def feasible_mixes(brand: BrandConstitution) -> list[tuple[int, ...]]:
    count = brand.cadence.posts_per_week
    ranges = [
        range(math.ceil(p.min_share * count - 1e-9), math.floor(p.max_share * count + 1e-9) + 1)
        for p in brand.pillars
    ]
    return [mix for mix in product(*ranges) if sum(mix) == count]


def _replace_arms(brand: BrandConstitution, template: list[Slot], arms: list[Arm]) -> list[Slot]:
    result = []
    for slot, arm in zip(template, arms, strict=True):
        clock = time.fromisoformat(brand.cadence.windows_cairo[arm.time_bucket])
        scheduled = datetime.combine(
            slot.scheduled_at.date(), clock, tzinfo=slot.scheduled_at.tzinfo
        )
        result.append(
            Slot.model_validate({**slot.model_dump(), "arm": arm, "scheduled_at": scheduled})
        )
    return result


def uniform_arms(brand: BrandConstitution, seed: int, week: int) -> list[Arm]:
    """FR-14: uniform constrained assignments, not argmax of random pillar scores."""
    rng = keyed_rng(seed, f"uniform:{week}")
    mixes = feasible_mixes(brand)
    weights = [
        math.factorial(brand.cadence.posts_per_week) // math.prod(math.factorial(n) for n in mix)
        for mix in mixes
    ]
    ticket = rng.randrange(sum(weights))
    chosen = mixes[-1]
    for mix, weight in zip(mixes, weights, strict=True):
        if ticket < weight:
            chosen = mix
            break
        ticket -= weight
    pillars = [p.id for p, n in zip(brand.pillars, chosen, strict=True) for _ in range(n)]
    rng.shuffle(pillars)
    formats = ["photo", "carousel", "reel"]
    while True:
        selected = [rng.choice(formats) for _ in pillars]
        if selected.count("reel") >= brand.cadence.min_reels:
            break
    buckets = list(brand.cadence.windows_cairo)
    hooks = ["question", "statement", "number"]
    bucket, hook = rng.choice(buckets), rng.choice(hooks)
    alternate_bucket = rng.choice([value for value in buckets if value != bucket])
    alternate_hook = rng.choice([value for value in hooks if value != hook])
    return [
        Arm.model_validate(
            {
                "pillar": pillar,
                "format": format,
                "time_bucket": alternate_bucket if index == 0 else bucket,
                "hook_style": alternate_hook if index == 0 else hook,
            }
        )
        for index, (pillar, format) in enumerate(zip(pillars, selected, strict=True))
    ]


class ConstrainedOracle:
    """FR-14: benchmark-only privileged reader of frozen logits; never fed to the optimizer."""

    def __init__(self, world: AudienceWorld, brand: BrandConstitution) -> None:
        self.world = world
        self.brand = brand
        self.rates = {
            arm.id: self._expected(arm)
            for pillar, format, bucket, hook in product(
                [p.id for p in brand.pillars],
                ("photo", "carousel", "reel"),
                list(brand.cadence.windows_cairo),
                ("question", "statement", "number"),
            )
            for arm in [
                Arm.model_validate(
                    {"pillar": pillar, "format": format, "time_bucket": bucket, "hook_style": hook}
                )
            ]
        }

    def _expected(self, arm: Arm) -> float:
        # Privileged access belongs only to the benchmark. Simulator bytes remain frozen.
        logit = self.world._logit(SimArm.model_validate(arm.model_dump()))
        sigma = self.world.config.noise_sigma
        if not sigma:
            return 1 / (1 + math.exp(-logit))
        # Simpson integration of sigmoid(logit + sigma*z) * standard normal density.
        steps, width = 128, 16 / 128
        total = 0.0
        for index in range(steps + 1):
            z = -8 + index * width
            weight = 1 if index in (0, steps) else 4 if index % 2 else 2
            total += (
                weight
                * math.exp(-z * z / 2)
                / math.sqrt(2 * math.pi)
                / (1 + math.exp(-(logit + sigma * z)))
            )
        return total * width / 3

    def rate(self, arm: Arm) -> float:
        return self.rates[arm.id]

    def reward(self, arms: list[Arm]) -> float:
        return sum(self.rate(arm) for arm in arms)

    def optimal(self) -> tuple[Arm, ...]:
        """FR-14: exact mix/first-pillar enumeration; cheapest reel substitutions meet min_reels."""
        best_reward = -1.0
        best_plan: tuple[Arm, ...] = ()
        buckets = list(self.brand.cadence.windows_cairo)
        hooks = ("question", "statement", "number")
        for bucket, hook, explore_bucket, explore_hook in product(buckets, hooks, buckets, hooks):
            if bucket == explore_bucket or hook == explore_hook:
                continue
            choices: dict[tuple[str, bool], tuple[Arm, Arm]] = {}
            for pillar in self.brand.pillars:
                for explore in (False, True):
                    candidates = [
                        Arm.model_validate(
                            {
                                "pillar": pillar.id,
                                "format": format,
                                "time_bucket": explore_bucket if explore else bucket,
                                "hook_style": explore_hook if explore else hook,
                            }
                        )
                        for format in ("photo", "carousel", "reel")
                    ]
                    choices[(pillar.id, explore)] = (max(candidates, key=self.rate), candidates[-1])
            for mix in feasible_mixes(self.brand):
                for first_index, first in enumerate(self.brand.pillars):
                    if not mix[first_index]:
                        continue
                    pillars = [first.id] + [
                        pillar.id
                        for index, (pillar, count) in enumerate(
                            zip(self.brand.pillars, mix, strict=True)
                        )
                        for _ in range(count - (index == first_index))
                    ]
                    pairs = [choices[(pillar, index == 0)] for index, pillar in enumerate(pillars)]
                    plan = [pair[0] for pair in pairs]
                    shortage = self.brand.cadence.min_reels - sum(a.format == "reel" for a in plan)
                    substitutions = sorted(
                        (i for i, arm in enumerate(plan) if arm.format != "reel"),
                        key=lambda i: self.rate(pairs[i][1]) - self.rate(plan[i]),
                        reverse=True,
                    )
                    for index in substitutions[: max(0, shortage)]:
                        plan[index] = pairs[index][1]
                    reward = self.reward(plan)
                    if reward > best_reward:
                        best_reward, best_plan = reward, tuple(plan)
        return best_plan


def evaluate_seed(
    brand: BrandConstitution, seed: int, weeks: int = 12
) -> tuple[list[SeedResult], list[PolicyWeek]]:
    """FR-14: shared observation IDs pair noise across policies; no publisher or approvals."""
    world = AudienceWorld(seed)
    oracle = ConstrainedOracle(world, brand)
    oracle_arms = list(oracle.optimal())
    digest = canonical_hash(brand)
    optimizer = ThompsonOptimizer(seed)
    fixed = plan_week(
        brand, digest, "w01", date(2026, 10, 12), optimizer.preferences(brand, [], "w01")
    )
    evidence = []
    results = []
    for policy in POLICIES:
        beliefs: dict[tuple[str, str], BetaPosterior] = {}
        history = []
        for week in range(1, weeks + 1):
            run_id = f"w{week:02d}"
            template = plan_week(
                brand, digest, run_id, date(2026, 10, 12) + timedelta(weeks=week - 1)
            )
            if policy == "fixed":
                plan = _replace_arms(brand, template, [slot.arm for slot in fixed])
            elif policy == "uniform":
                plan = _replace_arms(brand, template, uniform_arms(brand, seed, week))
            elif policy == "oracle":
                plan = _replace_arms(brand, template, oracle_arms)
            else:
                plan = plan_week(
                    brand,
                    digest,
                    run_id,
                    date(2026, 10, 12) + timedelta(weeks=week - 1),
                    optimizer.preferences(brand, list(beliefs.values()), run_id),
                )
            drift = (
                policy in ("leak_unguarded", "leak_guarded")
                and keyed_rng(seed, f"hook-drift:{week}").random() < 0.2
            )
            rotate = {"question": "statement", "statement": "number", "number": "question"}
            executed = [
                Arm.model_validate(
                    {**slot.arm.model_dump(), "hook_style": rotate[slot.arm.hook_style]}
                )
                if drift
                else slot.arm
                for slot in plan
            ]
            observations = [
                world.observe(
                    SimArm.model_validate(arm.model_dump()), f"w{week:02d}-post{index + 1}"
                )
                for index, arm in enumerate(executed)
            ]
            learned = 0
            if policy in ("thompson", "leak_unguarded", "leak_guarded"):
                for slot, observation in zip(plan, observations, strict=True):
                    if drift and policy == "leak_guarded":
                        continue
                    for factor, level in arm_levels(slot.arm):
                        previous = beliefs.get(
                            (factor, level), BetaPosterior(factor=factor, level=level)
                        )
                        beliefs[(factor, level)] = update_posterior(
                            previous, observation.engagement_rate
                        )
                    learned += 1
            reward = oracle.reward(executed)
            oracle_reward = oracle.reward(oracle_arms)
            row = PolicyWeek(
                seed=seed,
                policy=policy,
                week=week,
                rates=[o.engagement_rate for o in observations],
                reach=sum(o.reach for o in observations),
                engagements=sum(o.likes + o.comments + o.saved + o.shares for o in observations),
                planned=[slot.arm for slot in plan],
                executed=executed,
                leaked=len(plan) if drift else 0,
                learned=learned,
                expected_reward=reward,
                oracle_reward=oracle_reward,
                regret=oracle_reward - reward,
            )
            history.append(row)
            evidence.append(row)
        late_weeks = min(4, weeks)
        results.append(
            SeedResult(
                seed=seed,
                policy=policy,
                late_rate=mean(rate for row in history[-late_weeks:] for rate in row.rates),
                cumulative_regret=sum(row.regret for row in history),
                leaked=sum(row.leaked for row in history),
                learned=sum(row.learned for row in history),
            )
        )
    return results, evidence


def summarize(
    results: list[SeedResult], weeks: int = 12, resamples: int = 2000
) -> OptimizationMetric:
    """FR-14: ratio-of-means uplift and guarded-minus-unguarded regret use paired seeds."""
    seeds = sorted({row.seed for row in results})
    by_policy = {
        policy: sorted([row for row in results if row.policy == policy], key=lambda row: row.seed)
        for policy in POLICIES
    }
    if any([row.seed for row in rows] != seeds for rows in by_policy.values()):
        raise ValueError("Every policy must cover exactly the same unique seeds")
    summaries = {
        policy: PolicySummary(
            late_engagement_rate=bootstrap([row.late_rate for row in rows], resamples=resamples),
            cumulative_regret=bootstrap(
                [row.cumulative_regret for row in rows], resamples=resamples
            ),
            leaked_posts=sum(row.leaked for row in rows),
            learned_posts=sum(row.learned for row in rows),
        )
        for policy, rows in by_policy.items()
    }
    uplift = paired_bootstrap(
        [r.late_rate for r in by_policy["thompson"]],
        [r.late_rate for r in by_policy["fixed"]],
        relative_change,
        resamples=resamples,
    )
    difference = paired_bootstrap(
        [r.cumulative_regret for r in by_policy["leak_guarded"]],
        [r.cumulative_regret for r in by_policy["leak_unguarded"]],
        lambda a, b: mean(a) - mean(b),
        resamples=resamples,
    )
    return OptimizationMetric(
        weeks=weeks,
        posts_per_week=7,
        seeds=seeds,
        evaluation_weeks=list(range(max(1, weeks - 3), weeks + 1)),
        summaries=summaries,
        uplift=uplift,
        leakage_guard_regret_difference=difference,
        seed_results=results,
        assumptions=[
            "Frozen audience-v1; mean of post engagement rates; paired world-seed bootstrap",
            "Fixed policy repeats that seed's Thompson week-1 plan; optimizer unchanged",
            "Uniform feasible pillar sequences and reel-constrained formats; weekly hook/window "
            "with one alternate exploration slot",
            "Oracle optimizes this weekly hook/window family with pillar/reel constraints "
            "and an alternate first hook/window",
            "Synthetic leakage: predeclared 20% week-level hook rotation; preserves constraints",
            "D1-on is an ideal synthetic detector; no real engine calibration claim",
        ],
    )
