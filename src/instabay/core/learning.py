"""FR-11 to FR-13: validated measurements and content-bound fidelity evidence."""

from typing import Literal, Self

from pydantic import Field, model_validator

from instabay.core.schemas import Arm, Boundary, Hash, Identifier, UTCDateTime

Factor = Literal["pillar", "format", "time_bucket", "hook_style"]


class BetaPosterior(Boundary):
    """FR-13: positive factored Beta belief; no LLM controls its update."""

    factor: Factor
    level: Identifier
    alpha: float = Field(default=1, gt=0)
    beta: float = Field(default=1, gt=0)


class FidelityResult(Boundary):
    """FR-08, FR-13: only confirmed evidence of an unchanged arm enables learning."""

    post_id: Identifier
    content_hash: Hash
    planned_arm: Arm
    executed_arm: Arm | None = None
    status: Literal["confirmed", "leaked", "unverified"]
    source: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def arm_evidence(self) -> Self:
        if self.status == "confirmed" and self.executed_arm != self.planned_arm:
            raise ValueError("Confirmation requires a matching executed arm")
        if self.status == "leaked" and (
            self.executed_arm is None or self.executed_arm == self.planned_arm
        ):
            raise ValueError("Leakage requires a known different executed arm")
        return self


class MetricsSnapshot(Boundary):
    """FR-11: normalized insight payload; empty/missing insights must not become zeros."""

    post_id: Identifier
    content_hash: Hash
    source: str = Field(min_length=1)
    observed_at: UTCDateTime
    observed_arm: Arm
    arm_assumed: bool = False
    reach: int = Field(ge=1)
    views: int = Field(ge=1)
    likes: int = Field(ge=0)
    comments: int = Field(ge=0)
    saved: int = Field(ge=0)
    shares: int = Field(ge=0)
    watch_through: float | None = Field(default=None, ge=0, le=1)

    @property
    def engagement_rate(self) -> float:
        return (self.likes + self.comments + self.saved + self.shares) / self.reach

    @model_validator(mode="after")
    def bounded_reward(self) -> Self:
        if self.engagement_rate > 1 or self.views < self.reach:
            raise ValueError("Synthetic counts must give a bounded reward and views >= reach")
        if (self.watch_through is not None) != (self.observed_arm.format == "reel"):
            raise ValueError("Watch-through applies exactly to reels")
        return self

    def values(self) -> dict[str, float]:
        """FR-11: long-format values, including a derived bounded engagement rate."""
        result = {
            name: float(getattr(self, name))
            for name in ("reach", "views", "likes", "comments", "saved", "shares")
        }
        result["engagement_rate"] = self.engagement_rate
        if self.watch_through is not None:
            result["watch_through"] = self.watch_through
        return result


class LearningRecord(Boundary):
    """FR-13: one immutable observation/update receipt per published post."""

    scope_id: Hash
    metrics: MetricsSnapshot
    fidelity: FidelityResult
    learned: bool


class WeekAnalysis(Boundary):
    """FR-11, FR-13: descriptive synthetic results, not benchmark uplift claims."""

    run_id: Identifier
    exported: int = Field(ge=0)
    learned: int = Field(ge=0)
    leaked: int = Field(ge=0)
    unverified: int = Field(ge=0)
    reach: int = Field(ge=0)
    engagements: int = Field(ge=0)
    engagement_rate: float | None = Field(default=None, ge=0, le=1)
