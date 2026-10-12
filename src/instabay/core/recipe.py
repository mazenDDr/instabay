"""NFR-03, NFR-06: every render is addressed by its complete stored recipe."""

from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from instabay.core.schemas import Boundary, Hash, canonical_hash
from instabay.video.shotlist import FileRef, ShotList


class RuntimeIdentity(Boundary):
    """NFR-03: measured runtime identity, never fabricated native version defaults."""

    docker_image_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    python: str
    platform: str
    ffmpeg_sha256: Hash
    ffprobe_sha256: Hash
    implementation_sha256: Hash
    pillow: str
    reshaper: str
    bidi: str
    torch: str | None = None
    cuda: str | None = None
    driver: str | None = None
    gpu: str | None = None
    native_packages: dict[str, str] = Field(default_factory=dict)


class ModelIdentity(Boundary):
    """NFR-03: exact model/node files and scheduler configuration, not latest aliases."""

    repo: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    weights: list[FileRef] = Field(default_factory=list)
    loras: list[FileRef] = Field(default_factory=list)
    pipeline_class: str
    scheduler: str
    scheduler_config: dict[str, JsonValue] = Field(default_factory=dict)
    steps: int = Field(default=1, ge=1, le=100)
    cfg: float = Field(default=1, ge=0, le=30)
    shift: float = Field(default=1, gt=0, le=20)
    # HUMAN: verify this checkpoint actually supports last_image in the Phase 0 spike.
    supports_flf: bool = False
    workflow: FileRef | None = None
    custom_nodes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def pinned_nodes(self) -> Self:
        import re

        if any(
            not re.fullmatch(r"[0-9a-f]{40}", revision) for revision in self.custom_nodes.values()
        ):
            raise ValueError("Every custom node requires its exact commit")
        return self


class MotionSpec(Boundary):
    """FR-07: working resolution/fps; post always encodes 1080x1920 at 30 fps."""

    width: int = Field(default=360, ge=64, le=1920, multiple_of=2)
    height: int = Field(default=640, ge=64, le=1920, multiple_of=2)
    fps: int = Field(default=30, ge=12, le=60)
    frames: list[int] = Field(min_length=3)
    seeds: list[int] = Field(min_length=3)


class RecordedMotion(Boundary):
    """FR-06: recorded Wan clips preserve conditioning and provenance during CPU post."""

    backend: Literal["wan"] = "wan"
    recipe: FileRef
    recipe_hash: Hash
    conditioning_sha256: Hash
    clips: list[FileRef] = Field(min_length=3, max_length=10)


class PostSpec(Boundary):
    """NFR-08: font and optional LUT/audio bytes participate in the recipe hash."""

    font: FileRef
    lut: FileRef | None = None
    grain_strength: int = Field(default=0, ge=0, le=5)
    preset: Literal["ultrafast", "fast", "medium"] = "fast"
    crf: int = Field(default=23, ge=18, le=28)
    max_bytes: int = Field(default=300_000_000, gt=0, le=300_000_000)
    # [verify] conservative limits; HUMAN: verify current Meta specifications before live use.
    continuity_threshold: float = Field(default=0.9, ge=0, le=1)
    flicker_threshold: float = Field(default=0.08, ge=0, le=1)
    palette: list[str] = Field(default_factory=list)
    preview_label: str | None = Field(default=None, max_length=80)
    credit: str | None = Field(default=None, max_length=100)
    recorded_motion: RecordedMotion | None = None


class RenderRecipe(Boundary):
    """FR-06, NFR-03: immutable complete render inputs; L0 artifact cache is guaranteed."""

    version: Literal[1] = 1
    backend: Literal["stub", "wan", "comfyui", "veo"]
    shots: ShotList
    model: ModelIdentity
    motion: MotionSpec
    post: PostSpec
    runtime: RuntimeIdentity

    @model_validator(mode="after")
    def complete(self) -> Self:
        count = len(self.shots.shots)
        recorded = self.post.recorded_motion
        if recorded and (
            self.backend != "stub"
            or len(recorded.clips) != count
            or any(s.keyframe.sha256 != recorded.conditioning_sha256 for s in self.shots.shots)
        ):
            raise ValueError("Recorded CPU post requires matching clips and approved conditioning")
        if len(self.motion.frames) != count or len(self.motion.seeds) != count:
            raise ValueError("Every shot needs its frame count and seed")
        for shot, frames, seed in zip(
            self.shots.shots, self.motion.frames, self.motion.seeds, strict=True
        ):
            if (
                seed < 0
                or abs(frames / self.motion.fps - shot.seconds) > 1 / self.motion.fps + 1e-6
            ):
                raise ValueError("Frames/fps must match each shot's duration")
            if shot.end_keyframe and not self.model.supports_flf:
                raise ValueError("This recipe requests unsupported FLF conditioning")
        if self.backend != "stub":
            if any(s.keyframe.source == "synthetic" for s in self.shots.shots):
                raise ValueError("Synthetic fixtures cannot authorize native motion")
            if not self.model.weights or not all(
                (
                    self.runtime.docker_image_digest,
                    self.runtime.gpu,
                    self.runtime.torch,
                    self.runtime.cuda,
                    self.runtime.driver,
                )
            ):
                raise ValueError("Native motion requires weights and measured pinned GPU runtime")
        if self.backend == "wan" and (
            self.model.pipeline_class != "WanImageToVideoPipeline" or self.model.loras
        ):
            raise ValueError("Wan adapter supports verified I2V checkpoints without LoRAs")
        if self.backend == "comfyui" and (
            self.model.workflow is None or not self.model.custom_nodes
        ):
            raise ValueError("ComfyUI requires a pinned workflow and custom-node commits")
        return self

    @property
    def recipe_hash(self) -> str:
        return canonical_hash(self)

    @property
    def generated(self) -> bool:
        return (
            self.backend != "stub"
            or self.post.recorded_motion is not None
            or any(s.keyframe.source == "generated" for s in self.shots.shots)
        )

    @property
    def reference_only(self) -> bool:
        return self.post.recorded_motion is not None or any(
            s.keyframe.reference_only for s in self.shots.shots
        )
