"""FR-01 to FR-14: SQLModel SQLite tables; later-phase tables have no active logic yet."""

from typing import ClassVar

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class BrandVersionRow(SQLModel, table=True):
    """FR-01: content-addressed constitution plus human freeze provenance."""

    __tablename__: ClassVar[str] = "brand_version"
    hash: str = Field(primary_key=True)
    constitution_json: str
    frozen: bool = False
    actor: str | None = None
    frozen_at: str | None = None


class RunRow(SQLModel, table=True):
    """FR-03: offline demo runs are distinct from human-frozen brand runs."""

    __tablename__: ClassVar[str] = "workflow_run"
    id: str = Field(primary_key=True)
    week_start: str
    brand_hash: str = Field(foreign_key="brand_version.hash")
    demo: bool


class ArmRow(SQLModel, table=True):
    """FR-03: the four-factor tuple is a candidate key, separate from slots."""

    __tablename__: ClassVar[str] = "arm"
    __table_args__ = (UniqueConstraint("pillar", "format", "time_bucket", "hook_style"),)
    id: str = Field(primary_key=True)
    pillar: str
    format: str
    time_bucket: str
    hook_style: str


class SlotRow(SQLModel, table=True):
    """FR-03: store UTC schedules; domain reads convert back to Cairo."""

    __tablename__: ClassVar[str] = "slot"
    id: str = Field(primary_key=True)
    run_id: str = Field(foreign_key="workflow_run.id", index=True)
    brand_hash: str = Field(foreign_key="brand_version.hash")
    arm_id: str = Field(foreign_key="arm.id")
    scheduled_at: str
    segment: str
    explore: bool


class PostRow(SQLModel, table=True):
    """FR-04, FR-10: only content fields; arm/schedule come through the slot."""

    __tablename__: ClassVar[str] = "post"
    id: str = Field(primary_key=True)
    slot_id: str = Field(foreign_key="slot.id", unique=True)
    brief_json: str
    en_caption: str
    en_alt_text: str
    ar_caption: str
    ar_alt_text: str
    prompt_hashes_json: str
    revision: int
    ai_disclosure: bool
    offer_id: str | None = None
    media_path: str | None = None
    media_status: str
    idempotency_key: str


class HashtagRow(SQLModel, table=True):
    """FR-05: ordered hashtags are separate values, not a repeated post string."""

    __tablename__: ClassVar[str] = "post_hashtag"
    post_id: str = Field(primary_key=True, foreign_key="post.id")
    position: int = Field(primary_key=True)
    tag: str


class JudgeScoreRow(SQLModel, table=True):
    """FR-08: three sample rows per exact post snapshot, with written fixes."""

    __tablename__: ClassVar[str] = "judge_score"
    post_id: str = Field(primary_key=True, foreign_key="post.id")
    content_hash: str = Field(primary_key=True)
    sample: int = Field(primary_key=True)
    voice: int
    pillar_fit: int
    caption_visual_match: int
    hashtag_policy: int
    format_cta: int
    fixes_json: str


class ReviewRow(SQLModel, table=True):
    """FR-08: current deterministic rule outcome and queue flags."""

    __tablename__: ClassVar[str] = "review"
    post_id: str = Field(primary_key=True, foreign_key="post.id")
    content_hash: str
    rules_passed: bool
    violations_json: str
    arabic_ratio: float
    flags_json: str


class ApprovalRow(SQLModel, table=True):
    """FR-09: append-only decisions with exact content binding and timed edits."""

    __tablename__: ClassVar[str] = "approval"
    sequence: int | None = Field(default=None, primary_key=True)
    id: str = Field(unique=True)
    post_id: str = Field(foreign_key="post.id", index=True)
    content_hash: str
    decision: str
    actor: str
    reason: str
    diff_json: str
    seconds_spent: float
    decided_at: str


class PublicationRow(SQLModel, table=True):
    """FR-10: one immutable receipt for each idempotent export."""

    __tablename__: ClassVar[str] = "publication"
    id: str = Field(primary_key=True)
    post_id: str = Field(foreign_key="post.id", unique=True)
    approval_id: str = Field(foreign_key="approval.id")
    idempotency_key: str = Field(unique=True)
    content_hash: str
    mode: str
    outbox_path: str
    published_at: str


class DecisionScoreRow(SQLModel, table=True):
    """FR-08: provision schema; decision engines are implemented in Phase 6."""

    __tablename__: ClassVar[str] = "decision_score"
    id: str = Field(primary_key=True)
    post_id: str = Field(foreign_key="post.id")
    engine: str
    question_id: str
    answer_json: str
    confidence: float
    escalated: bool


class MetricRow(SQLModel, table=True):
    """FR-11: long-format insights; no simulator or Graph calls in Phase 2."""

    __tablename__: ClassVar[str] = "metric"
    post_id: str = Field(primary_key=True, foreign_key="post.id")
    name: str = Field(primary_key=True)
    observed_at: str = Field(primary_key=True)
    value: float
    source: str


class PosteriorRow(SQLModel, table=True):
    """FR-13: storage schema only; no posterior updates before the simulator commit."""

    __tablename__: ClassVar[str] = "posterior"
    factor: str = Field(primary_key=True)
    level: str = Field(primary_key=True)
    alpha: float
    beta: float


class RenderJobRow(SQLModel, table=True):
    """FR-06, NFR-03: render metadata schema; Phase 7 supplies executable recipes."""

    __tablename__: ClassVar[str] = "render_job"
    recipe_hash: str = Field(primary_key=True)
    recipe_json: str
    backend: str
    status: str
    gpu: str | None = None
    seconds: float
    frame_hashes_json: str
    qa_json: str
    cost_usd: float
