"""FR-11, NFR-07: hidden audience, frozen before any optimizer implementation (§9)."""

import hashlib
import math
import random
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class SimBoundary(BaseModel):
    """NFR-07: immutable finite simulator boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SimArm(SimBoundary):
    """FR-11: an executed arm; the simulator has no planner or optimizer dependency."""

    pillar: str = Field(min_length=1)
    format: Literal["photo", "carousel", "reel"]
    time_bucket: Literal["morning_08_10", "noon_12_14", "evening_19_21", "late_21_23"]
    hook_style: Literal["question", "statement", "number"]


class WorldConfig(SimBoundary):
    """FR-11: predeclared synthetic constants, not fitted to optimizer performance."""

    version: Literal["audience-v1"] = "audience-v1"
    pillars: tuple[str, ...] = ("underwater", "spa", "guests", "local", "offers")
    log_reach: float = 7.3
    reach_sigma: float = Field(default=0.35, gt=0)
    base_logit: float = -3.0
    coefficient_sigma: float = Field(default=0.3, gt=0)
    noise_sigma: float = Field(default=0.1, ge=0)

    @model_validator(mode="after")
    def distinct_pillars(self) -> Self:
        if not self.pillars or len(set(self.pillars)) != len(self.pillars):
            raise ValueError("Pillars must be nonempty and unique")
        if any(not item.strip() for item in self.pillars):
            raise ValueError("Pillar names must be nonempty")
        return self


class Observation(SimBoundary):
    """FR-11: mutually exclusive engagement counts, not real Instagram measurements."""

    world_seed: int
    event_id: str = Field(min_length=1)
    arm: SimArm
    reach: int = Field(ge=1)
    views: int = Field(ge=1)
    likes: int = Field(ge=0)
    comments: int = Field(ge=0)
    saved: int = Field(ge=0)
    shares: int = Field(ge=0)
    watch_through: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if self.likes + self.comments + self.saved + self.shares > self.reach:
            raise ValueError("Exclusive engagement count exceeds reach")
        if self.views < self.reach:
            raise ValueError("Views cannot be below reach")
        if (self.watch_through is not None) != (self.arm.format == "reel"):
            raise ValueError("Watch-through applies exactly to reels")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def engagement_rate(self) -> float:
        return (self.likes + self.comments + self.saved + self.shares) / self.reach


def _rng(seed: int, key: str) -> random.Random:
    digest = hashlib.sha256(f"audience-v1:{seed}:{key}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


class AudienceWorld:
    """FR-11: stateless observations, stable across retries and policy call ordering."""

    def __init__(self, seed: int, config: WorldConfig | None = None) -> None:
        self.seed = seed
        self.config = config or WorldConfig()
        levels = {
            "pillar": self.config.pillars,
            "format": ("photo", "carousel", "reel"),
            "time_bucket": ("morning_08_10", "noon_12_14", "evening_19_21", "late_21_23"),
            "hook_style": ("question", "statement", "number"),
        }
        self._effects = {
            (factor, level): _rng(seed, f"effect:{factor}:{level}").gauss(
                0, self.config.coefficient_sigma
            )
            for factor, names in levels.items()
            for level in names
        }
        self._reach_effects = {
            (factor, level): _rng(seed, f"reach:{factor}:{level}").gauss(0, 0.15)
            for factor in ("format", "time_bucket")
            for level in levels[factor]
        }

    def _logit(self, arm: SimArm) -> float:
        arm = SimArm.model_validate(arm.model_dump())
        if arm.pillar not in self.config.pillars:
            raise ValueError("Unknown simulator pillar")
        return self.config.base_logit + sum(
            self._effects[(factor, str(level))] for factor, level in arm.model_dump().items()
        )

    def observe(self, arm: SimArm, event_id: str) -> Observation:
        """FR-11: LogNormal reach, Binomial engagement and hook-dependent Beta watch-through."""
        if not event_id.strip():
            raise ValueError("An observation needs a stable event ID")
        logit = self._logit(arm)
        rng = _rng(self.seed, f"event:{event_id}")
        mu = self.config.log_reach + self._reach_effects[("format", arm.format)]
        mu += self._reach_effects[("time_bucket", arm.time_bucket)]
        reach = max(1, round(rng.lognormvariate(mu, self.config.reach_sigma)))
        noisy_logit = logit + rng.gauss(0, self.config.noise_sigma)
        probability = 1 / (1 + math.exp(-noisy_logit))
        engaged = rng.binomialvariate(reach, probability)
        likes = rng.binomialvariate(engaged, 0.75)
        remaining = engaged - likes
        comments = rng.binomialvariate(remaining, 0.07 / 0.25)
        remaining -= comments
        saved = rng.binomialvariate(remaining, 0.12 / 0.18)
        watch = None
        if arm.format == "reel":
            hook_logit = self._effects[("hook_style", arm.hook_style)]
            mean = 1 / (1 + math.exp(-hook_logit))
            watch = rng.betavariate(8 * mean, 8 * (1 - mean))
        return Observation(
            world_seed=self.seed,
            event_id=event_id,
            arm=arm,
            reach=reach,
            views=reach + rng.binomialvariate(reach, 0.6 if arm.format == "reel" else 0.3),
            likes=likes,
            comments=comments,
            saved=saved,
            shares=remaining - saved,
            watch_through=watch,
        )
