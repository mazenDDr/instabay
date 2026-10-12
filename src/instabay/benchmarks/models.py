"""FR-14: result schema distinguishes observations, synthetic scores and missing human data."""

from datetime import date
from typing import Literal

from pydantic import Field

from instabay.adapters.call_store import CallRecord
from instabay.benchmarks.policies import OptimizationMetric
from instabay.benchmarks.statistics import Estimate
from instabay.core.schemas import Boundary, Hash, Post, Review, Slot, UTCDateTime


class ArabicScores(Boundary):
    """FR-14: the three Arabic-quality dimensions, independently schema validated."""

    fluency: int = Field(ge=1, le=5)
    naturalness: int = Field(ge=1, le=5)
    brand_voice: int = Field(ge=1, le=5)

    @property
    def average(self) -> float:
        return (self.fluency + self.naturalness + self.brand_voice) / 3


class ContentEvidence(Boundary):
    """FR-14, NFR-06: intermediate content, checks and cold-call evidence per fixed post."""

    slot: Slot
    post: Post
    review: Review
    calls: list[CallRecord]
    wall_latency_ms: float = Field(ge=0)
    arabic_samples: list[ArabicScores] = Field(min_length=3, max_length=3)


class BrandMetric(Boundary):
    """FR-14: fixture judge numbers stay uncalibrated until labeled by a human."""

    judge_mean: Estimate
    hard_rule_pass_rate: Estimate
    negative_control_mean: Estimate
    negative_control_gap: Estimate
    negative_control_clearly_lower: bool
    quadratic_weighted_kappa: float | None
    labeled_posts: int
    calibration_status: Literal["pending_human", "partial_human", "human_labels_available"]
    score_provenance: Literal["illustrative_fake_llm"] = "illustrative_fake_llm"


class ArabicMetric(Boundary):
    """FR-14: blind human comparison values remain null when ratings are absent."""

    judge_mean: Estimate
    native_mean: Estimate | None
    mt_mean: Estimate | None
    native_win_rate: Estimate | None
    krippendorff_alpha_interval: float | None
    judge_human_spearman: float | None
    rated_items: int
    unique_native_captions: int
    unique_translation_captions: int
    paired_posts: int
    raters: int
    status: Literal["pending_human", "partial_human", "human_labels_available"]
    comparison_provenance: str


class PriceCard(Boundary):
    """FR-14: a human-supplied model-specific paid list price with attribution/date."""

    model: str = Field(min_length=1)
    input_usd_per_million: float = Field(ge=0)
    output_usd_per_million: float = Field(ge=0)
    source: str = Field(min_length=1)
    verified_on: date


class EfficiencyGroup(Boundary):
    """FR-14: pipeline costs per post; wall and provider-sum latency are distinct."""

    posts: int
    input_tokens: int
    output_tokens: int
    calls: int
    actual_spend_usd: float
    paid_list_price_usd: float | None
    mean_input_tokens: Estimate
    mean_output_tokens: Estimate
    mean_actual_spend_usd: Estimate
    mean_paid_list_price_usd: Estimate | None
    mean_wall_latency_ms: Estimate
    wall_p50_ms: float
    wall_p95_ms: float
    provider_sum_p50_ms: float
    provider_sum_p95_ms: float


class EfficiencyMetric(Boundary):
    """FR-14: recorded fixture tokens and local replay timing do not measure real providers."""

    groups: dict[Literal["feed", "reel_concept"], EfficiencyGroup]
    shared_brand_input_tokens: int
    shared_brand_output_tokens: int
    shared_brand_actual_spend_usd: float
    benchmark_evaluation_calls: int
    benchmark_evaluation_input_tokens: int
    benchmark_evaluation_output_tokens: int
    render_jobs: int = 0
    price_cards: list[PriceCard]
    missing_price_models: list[str]
    provenance: str


class HumanTouchpoint(Boundary):
    """FR-14: timed feedback is measurement data only, never publishing authorization."""

    post_id: str
    decision: Literal["APPROVED", "EDITED", "REJECTED"]
    reason: str
    seconds_spent: float = Field(ge=0)


class AutonomyMetric(Boundary):
    """FR-14: topology coverage and missing operational autonomy cannot be conflated."""

    configured_steps: int
    automatic_steps: int
    configured_automation_share: float
    observed_completed_automatic_steps: int
    pending_human_steps: int
    blocked_downstream_steps: int
    measured_full_pipeline_automation_share: float | None = None
    human_minutes_per_week: Estimate | None
    first_pass_approval_rate: Estimate | None
    touchpoints: list[HumanTouchpoint]
    status: str


class BenchmarkResults(Boundary):
    """FR-14: the five required metrics have explicit provenance and missing-data status."""

    schema_version: Literal["bench-v1"] = "bench-v1"
    generated_at: UTCDateTime
    mode: Literal["offline_fixture"] = "offline_fixture"
    protocol_hash: Hash
    corpus_hash: Hash
    corpus_posts: int
    environment: dict[str, str]
    brand_consistency: BrandMetric
    arabic_quality: ArabicMetric
    optimization_uplift: OptimizationMetric
    efficiency: EfficiencyMetric
    autonomy: AutonomyMetric
    human_pending: list[str]
