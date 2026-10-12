"""FR-01 to FR-10: validated domain boundaries for the approval-first weekly loop."""

import hashlib
import ipaddress
import json
import math
import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

CAIRO = ZoneInfo("Africa/Cairo")
PostFormat = Literal["photo", "carousel", "reel"]
HookStyle = Literal["question", "statement", "number"]
TimeBucket = Literal["morning_08_10", "noon_12_14", "evening_19_21", "late_21_23"]
ApprovalDecision = Literal["APPROVED", "EDITED", "REJECTED"]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def utc(value: datetime) -> datetime:
    """NFR-06: normalize timezone-aware database timestamps to UTC."""
    return value.astimezone(UTC)


UTCDateTime = Annotated[AwareDatetime, AfterValidator(utc)]


def canonical_hash(value: BaseModel | dict[str, object]) -> str:
    """NFR-03: hash deterministic JSON rather than Python object representations."""
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Boundary(BaseModel):
    """NFR-03: all domain objects reject unknown fields and non-finite numbers."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        serialize_by_alias=True,
        validate_by_name=True,
    )


class Voice(Boundary):
    """FR-01: native voice instructions and examples for one language."""

    do: list[str]
    dont: list[str]
    examples: list[str] = Field(min_length=1)


class ArabicVoice(Voice):
    """FR-01: register is explicit, defaulting to light MSA."""

    register_: Literal["light_msa", "msa", "egyptian", "gulf"] = Field(
        default="light_msa", alias="register"
    )


class Voices(Boundary):
    """FR-01: EN and AR guidelines share positioning, not translated copy."""

    en: Voice
    ar: ArabicVoice


class Pillar(Boundary):
    """FR-02: minimum/maximum proportions constrain every weekly plan."""

    id: Identifier
    description: str = Field(min_length=1)
    min_share: float = Field(ge=0, le=1)
    max_share: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        if self.min_share > self.max_share:
            raise ValueError("Pillar minimum must not exceed maximum")
        return self


class HashtagBank(Boundary):
    """FR-05: validated tiered bilingual bank, selected in code."""

    branded: list[str] = Field(min_length=1)
    place: list[str]
    niche: list[str]
    broad: list[str]

    @model_validator(mode="after")
    def valid_tags(self) -> Self:
        tags = self.branded + self.place + self.niche + self.broad
        if any(not tag.startswith("#") or not tag[1:].replace("_", "").isalnum() for tag in tags):
            raise ValueError("Hashtags must contain letters, numbers or underscores after #")
        if len(set(tags)) < 8:
            raise ValueError("At least eight unique hashtags are required")
        return self


class Cadence(Boundary):
    """FR-02: configured Cairo windows must respect mandatory quiet hours."""

    posts_per_week: int = Field(default=7, ge=1, le=7)
    min_reels: int = Field(default=1, ge=1)
    windows_cairo: dict[TimeBucket, str]

    @model_validator(mode="after")
    def valid_windows(self) -> Self:
        if self.min_reels > self.posts_per_week or not self.windows_cairo:
            raise ValueError("Reel count and windows must fit the cadence")
        for text in self.windows_cairo.values():
            try:
                hour, minute = (int(part) for part in text.split(":"))
            except ValueError as error:
                raise ValueError("Posting windows must be HH:MM") from error
            if not 0 <= hour <= 23 or not 0 <= minute <= 59 or 1 <= hour < 7:
                raise ValueError("Posting window violates clock or quiet-hour bounds")
        return self


class VisualPolicy(Boundary):
    """FR-01: palette, approved photo direction and visual exclusions."""

    palette_hex: list[Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]]
    photo_direction: str
    banned: list[str]


class ClaimsPolicy(Boundary):
    """FR-08: claim/offer sources are explicit, never inferred from resort references."""

    no_invented_facilities: Literal[True] = True
    verified_facilities: list[str] = Field(default_factory=list)
    facility_terms: list[str]
    allowed_offers: dict[str, str] = Field(default_factory=dict)
    banned_terms: list[str]
    emoji_budget: int = Field(default=2, ge=0, le=2)

    @model_validator(mode="after")
    def source_backed_offers(self) -> Self:
        if any(
            not key.strip() or not source.strip() for key, source in self.allowed_offers.items()
        ):
            raise ValueError("Every allowed offer requires a nonempty ID and source")
        return self


class BrandConstitution(Boundary):
    """FR-01: a human freezes this object; demo fixtures remain explicitly unfrozen."""

    version: int = Field(ge=1)
    positioning: str = Field(min_length=1)
    voice: Voices
    pillars: list[Pillar] = Field(min_length=5, max_length=5)
    hashtags: HashtagBank
    cadence: Cadence
    visual: VisualPolicy
    claims_policy: ClaimsPolicy
    judge_threshold: float = Field(default=4, ge=1, le=5)

    @model_validator(mode="after")
    def feasible_mix(self) -> Self:
        if len({pillar.id for pillar in self.pillars}) != len(self.pillars):
            raise ValueError("Pillar identifiers must be unique")
        if sum(p.min_share for p in self.pillars) > 1 + 1e-9:
            raise ValueError("Pillar minima sum to more than one")
        if sum(p.max_share for p in self.pillars) < 1 - 1e-9:
            raise ValueError("Pillar maxima sum to less than one")
        count = self.cadence.posts_per_week
        minimum = sum(math.ceil(p.min_share * count - 1e-9) for p in self.pillars)
        maximum = sum(math.floor(p.max_share * count + 1e-9) for p in self.pillars)
        if not minimum <= count <= maximum:
            raise ValueError("Pillar bounds have no feasible integer weekly allocation")
        return self


class BrandInput(Boundary):
    """FR-01: brief and human-provided facts enter through a typed boundary."""

    brief: str = Field(min_length=1)
    owner_answers: dict[str, list[str]]


class Arm(Boundary):
    """FR-03: factor tuple selected by code; optimizer behavior comes in Phase 3."""

    pillar: Identifier
    format: PostFormat
    time_bucket: TimeBucket
    hook_style: HookStyle

    @property
    def id(self) -> str:
        return canonical_hash(self)


class PlanningPreferences(Boundary):
    """FR-02: finite scores supplied to the planner; neutral defaults in Phase 2."""

    pillar: dict[str, float] = Field(default_factory=dict)
    format: dict[PostFormat, float] = Field(default_factory=dict)
    time_bucket: dict[TimeBucket, float] = Field(default_factory=dict)
    hook_style: dict[HookStyle, float] = Field(default_factory=dict)


class Slot(Boundary):
    """FR-03: aware schedule normalized to Cairo, with explicit exploration."""

    id: Identifier
    run_id: Identifier
    brand_hash: Hash
    scheduled_at: AwareDatetime
    arm: Arm
    segment: Literal["egyptian", "gcc", "european"]
    explore: bool

    @model_validator(mode="after")
    def cairo_time(self) -> Self:
        localized = self.scheduled_at.astimezone(CAIRO)
        if 1 <= localized.hour < 7:
            raise ValueError("Slot falls in Cairo quiet hours")
        object.__setattr__(self, "scheduled_at", localized)
        return self


class ReelConcept(Boundary):
    """FR-06: concept only; executable shot recipes/renders arrive in Phase 7."""

    hook: str
    shots: list[str] = Field(min_length=1)
    overlay_en: str
    overlay_ar: str
    audio: str
    cta: str
    cover: str


class Brief(Boundary):
    """FR-04, FR-06: one shared brief feeds both native writers."""

    angle: str
    hook: str
    key_message: str
    visual_description: str
    photo_uri: str
    cta: str
    must_not: list[str]
    reel_concept: ReelConcept | None = None


class Copy(Boundary):
    """FR-04: native caption and visual description, before code adds hashtags."""

    caption: str = Field(min_length=1, max_length=2200)
    alt_text: str = Field(min_length=1)


class MediaAsset(Boundary):
    """FR-07: HUMAN-verified metadata and public immutable bytes bound into approval."""

    url: str
    content_sha256: Hash
    kind: Literal["image", "video"]
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: Literal["image/jpeg", "video/mp4", "video/quicktime"]
    color_space: Literal["sRGB"] | None = None
    duration_s: float | None = Field(default=None, ge=3, le=900)
    fps: float | None = Field(default=None, ge=23, le=60)
    video_codec: Literal["h264", "hevc"] | None = None
    audio_codec: Literal["aac"] | None = None
    audio_sample_rate: int | None = Field(default=None, gt=0, le=48000)
    moov_at_front: bool = False

    @field_validator("url")
    @classmethod
    def public_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
            or host == "localhost"
            or host.endswith((".local", ".internal"))
        ):
            raise ValueError("Media needs a public HTTPS URL without credentials/query/fragment")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError("Media host must be a public domain") from None
        else:
            if not address.is_global:
                raise ValueError("Private/local media IPs are forbidden")
        return value

    @model_validator(mode="after")
    def media_spec(self) -> Self:
        if self.kind == "image":
            if (
                self.mime_type != "image/jpeg"
                or self.color_space != "sRGB"
                or not 0.8 <= self.width / self.height <= 1.91
            ):
                raise ValueError("Images require sRGB JPEG and aspect ratio 4:5 to 1.91:1")
        elif (
            self.mime_type == "image/jpeg"
            or self.width > 1920
            or self.duration_s is None
            or self.fps is None
            or self.video_codec is None
            or self.audio_codec is None
            or self.audio_sample_rate is None
            or not self.moov_at_front
        ):
            raise ValueError("Video requires verified codecs, timing, dimensions and fast-start")
        return self


class MediaManifest(Boundary):
    """FR-07, NFR-03: included in the stored post hash before human approval."""

    format: PostFormat
    assets: list[MediaAsset] = Field(min_length=1, max_length=10)
    cover: MediaAsset | None = None
    reference_only: bool = True
    verified_by: str = Field(min_length=1)
    # HUMAN: verify bytes/specs/rights and facility fidelity before attaching this manifest.
    generated: bool = False
    recipe_hash: Hash | None = None
    render_recipe: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def format_spec(self) -> Self:
        count = len(self.assets)
        if self.format == "photo" and (count != 1 or self.assets[0].kind != "image"):
            raise ValueError("Photo requires one image")
        if self.format == "carousel" and (
            not 2 <= count <= 10 or any(a.kind != "image" for a in self.assets)
        ):
            raise ValueError("This carousel adapter supports 2-10 images")
        if self.format == "reel":
            if count != 1 or self.assets[0].kind != "video":
                raise ValueError("Reel requires one video")
            if self.render_recipe is None or self.recipe_hash != canonical_hash(
                cast(dict[str, object], self.render_recipe)
            ):
                raise ValueError("Reel needs a stored recipe with its exact canonical hash")
        if self.cover is not None and (self.format != "reel" or self.cover.kind != "image"):
            raise ValueError("Only reels may have an image cover")
        return self


class Post(Boundary):
    """FR-04 to FR-10: immutable content snapshot; approval binds its exact hash."""

    id: Identifier
    slot_id: Identifier
    brand_hash: Hash
    format: PostFormat
    brief: Brief
    en: Copy
    ar: Copy
    hashtags: list[str] = Field(min_length=8, max_length=15)
    prompt_hashes: dict[str, Hash]
    revision: int = Field(default=0, ge=0)
    ai_disclosure: bool = False
    offer_id: str | None = None
    media_path: str | None = None
    media_status: Literal["reference", "concept_only", "rendered", "ready"] = "reference"
    media_manifest: MediaManifest | None = Field(default=None, exclude_if=lambda v: v is None)

    @property
    def content_hash(self) -> str:
        return canonical_hash(self)

    @property
    def idempotency_key(self) -> str:
        return canonical_hash(
            {
                "slot_id": self.slot_id,
                "brand_hash": self.brand_hash,
                "prompt_hashes": self.prompt_hashes,
                "content_hash": self.content_hash,
            }
        )

    def full_caption(self, language: Literal["en", "ar"]) -> str:
        """FR-05: checks and exports use the actual final caption length."""
        caption = (self.en if language == "en" else self.ar).caption
        if self.ai_disclosure:
            caption += (
                "\nScenes created with AI."
                if language == "en"
                else "\nمشاهد أُنشئت بالذكاء الاصطناعي."
            )
        return caption + "\n" + " ".join(self.hashtags)


class RuleResult(Boundary):
    """FR-08: explainable deterministic checks against the exact content snapshot."""

    post_id: Identifier
    content_hash: Hash
    passed: bool
    violations: list[str]
    arabic_ratio: float = Field(ge=0, le=1)


class RubricScores(Boundary):
    """FR-08: five bounded rubric dimensions, averaged by code."""

    voice: int = Field(ge=1, le=5)
    pillar_fit: int = Field(ge=1, le=5)
    caption_visual_match: int = Field(ge=1, le=5)
    hashtag_policy: int = Field(ge=1, le=5)
    format_cta: int = Field(ge=1, le=5)

    @property
    def average(self) -> float:
        return (
            self.voice
            + self.pillar_fit
            + self.caption_visual_match
            + self.hashtag_policy
            + self.format_cta
        ) / 5


class JudgeSample(Boundary):
    """FR-08: one independent request supplies scores and actionable fixes."""

    scores: RubricScores
    fixes: list[str]


class JudgeResult(Boundary):
    """FR-08: mean of three separately recorded judge requests."""

    content_hash: Hash
    samples: list[JudgeSample] = Field(min_length=3, max_length=3)
    average: float = Field(ge=1, le=5)
    passed: bool
    fixes: list[str]


class Review(Boundary):
    """FR-08, FR-09: rules, scores and flags shown at the approval interrupt."""

    post_id: Identifier
    content_hash: Hash
    rules: RuleResult
    judge: JudgeResult
    flagged: bool
    flags: list[str]


class ApprovalRequest(Boundary):
    """FR-09: an explicit human decision; edits must change at least one caption."""

    decision: ApprovalDecision
    actor: str = Field(min_length=1)
    reason: str = ""
    seconds_spent: float = Field(ge=0)
    en_caption: str | None = Field(default=None, min_length=1, max_length=2200)
    ar_caption: str | None = Field(default=None, min_length=1, max_length=2200)

    @model_validator(mode="after")
    def valid_edit(self) -> Self:
        edits = self.en_caption is not None or self.ar_caption is not None
        if (self.decision == "EDITED") != edits:
            raise ValueError(
                "Only EDITED decisions may contain caption changes, and require a change"
            )
        if self.decision == "REJECTED" and not self.reason.strip():
            raise ValueError("A rejection needs a reason")
        return self


class Approval(Boundary):
    """FR-09: stored human decision tied to the precise approved content."""

    id: str
    post_id: Identifier
    content_hash: Hash
    decision: ApprovalDecision
    actor: str
    reason: str
    diff: dict[str, str]
    seconds_spent: float = Field(ge=0)
    decided_at: UTCDateTime


class Publication(Boundary):
    """FR-10: export or live receipt; live IDs require explicit remote provenance."""

    id: str
    post_id: Identifier
    approval_id: str
    idempotency_key: Hash
    content_hash: Hash
    mode: Literal["dry_run", "live"] = "dry_run"
    media_id: str | None = None
    container_id: str | None = None
    account_id: str | None = None
    api_version: str | None = None
    payload_hash: Hash | None = None
    graph_login: Literal["instagram", "facebook"] | None = None
    outbox_path: str
    published_at: UTCDateTime

    @model_validator(mode="after")
    def mode_provenance(self) -> Self:
        remote = (
            self.media_id,
            self.container_id,
            self.account_id,
            self.api_version,
            self.payload_hash,
            self.graph_login,
        )
        if self.mode == "live":
            if not all(remote) or self.outbox_path:
                raise ValueError("Live receipt needs remote IDs/profile and no outbox path")
            if any(not re.fullmatch(r"[0-9]+", value or "") for value in remote[:3]):
                raise ValueError("Live resource IDs must be numeric")
        elif any(remote):
            raise ValueError("Dry-run exports cannot claim live Graph provenance")
        return self


class WorkflowInput(Boundary):
    """FR-03: deterministic offline run identity and Monday start date."""

    run_id: Identifier
    week_start: date
    demo: bool = True


class WorkflowResult(Boundary):
    """FR-09: resumable weekly graph result, validated before CLI output."""

    run_id: Identifier
    post_ids: list[str]
    status: Literal["approval_pending", "in_progress", "completed"]
