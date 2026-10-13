"""FR-06, NFR-08: approved stills and native bilingual overlays precede motion."""

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from instabay.core.schemas import Boundary, Hash, Identifier

LocalPath = Annotated[str, Field(pattern=r"^[A-Za-z0-9_./-]+$")]


class FileRef(Boundary):
    """NFR-03: local, immutable input bytes; no remote URLs or traversal."""

    uri: LocalPath
    sha256: Hash

    @field_validator("uri")
    @classmethod
    def relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("Inputs must be canonical relative paths")
        return value


class Keyframe(FileRef):
    """FR-07, NFR-04: approvals attest fidelity; fixtures cannot authorize native work."""

    source: Literal["photo", "generated", "synthetic"]
    scene: Literal["mood", "facility"] = "mood"
    approved_by: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    approval_scope: Literal["crop", "preview_source_use", "owner_approved_view"] = Field(
        default="crop", exclude_if=lambda v: v == "crop"
    )
    reference_only: bool = True
    faces_checked: Literal[True]
    attribution: str = Field(min_length=1)
    prompt: str | None = None
    seed: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def honest_scenery(self) -> Self:
        if self.scene == "facility" and self.source != "photo":
            raise ValueError("Facility shots must originate from real photos")
        if self.source == "generated" and (not self.prompt or self.seed is None):
            raise ValueError("Generated stills need their prompt and seed")
        if (
            self.source == "synthetic"
            and not self.reference_only
            and self.approval_scope != "owner_approved_view"
        ):
            raise ValueError("Synthetic fixtures are reference-only")
        if self.approval_scope == "preview_source_use" and not self.reference_only:
            raise ValueError(
                "Source-selection authorization cannot approve production property media"
            )
        return self


class Overlay(Boundary):
    """FR-06, NFR-08: short independent EN/AR copy added only in post."""

    en: str = Field(max_length=120)
    ar: str = Field(max_length=120)


class SourceClip(FileRef):
    """FR-06: real or generated motion is separate from approval of its reference photo."""

    generated: bool
    reference_only: bool = True
    credit: str = Field(min_length=1)
    motion_recipe: FileRef | None = None
    motion_recipe_hash: Hash | None = None
    start_s: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def provenance(self) -> Self:
        if self.generated and (
            not self.motion_recipe or not self.motion_recipe_hash or not self.reference_only
        ):
            raise ValueError(
                "Generated editorial clips need stored reference-only motion provenance"
            )
        return self


class Shot(Boundary):
    """FR-06: short shots; explicit next-keyframe conditioning, never silent fallback."""

    id: Identifier
    role: Literal["hook", "body", "cta"]
    keyframe: Keyframe
    end_keyframe: Identifier | None = None
    motion_prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(min_length=1, max_length=2000)
    camera: Literal[
        "static", "push_in", "pull_out", "pan_left", "pan_right", "orbit", "tilt_up", "tilt_down"
    ]
    seconds: float = Field(ge=0.5, le=7)
    overlay: Overlay
    motion_strength: float = Field(default=0.06, ge=0, le=0.25)
    source_clip: SourceClip | None = None
    text_start_s: float = Field(default=0, ge=0)
    text_end_s: float | None = Field(default=None, ge=0)
    text_position: Literal["upper", "lower"] = "lower"

    @model_validator(mode="after")
    def text_window(self) -> Self:
        end = self.text_end_s if self.text_end_s is not None else self.seconds
        if not self.text_start_s < end <= self.seconds:
            raise ValueError("Text window must fit inside its shot")
        return self


class Audio(Boundary):
    """FR-06: silence by default; music/voiceover are already licensed local files."""

    music: FileRef | None = None
    music_credit: str | None = None
    voiceover: FileRef | None = None
    voiceover_lang: Literal["en", "ar"] | None = None

    @model_validator(mode="after")
    def credits(self) -> Self:
        if self.music is not None and not self.music_credit:
            raise ValueError("Music requires rights/attribution evidence")
        if (self.voiceover is None) != (self.voiceover_lang is None):
            raise ValueError("Voiceover requires its language")
        return self


class ShotList(Boundary):
    """FR-06: 15-30 second reel with validated FLF references and total timing."""

    reel_id: Identifier
    duration_s: int = Field(ge=15, le=30)
    aspect: Literal["9:16"] = "9:16"
    shots: list[Shot] = Field(min_length=3, max_length=10)
    audio: Audio = Audio()

    @model_validator(mode="after")
    def sequence(self) -> Self:
        ids = [s.id for s in self.shots]
        if (
            len(set(ids)) != len(ids)
            or abs(sum(s.seconds for s in self.shots) - self.duration_s) > 1e-6
        ):
            raise ValueError("Shot IDs and total duration must match")
        if self.shots[0].role != "hook" or self.shots[-1].role != "cta":
            raise ValueError("Reel must open with a hook and end with a CTA")
        for index, shot in enumerate(self.shots):
            if shot.end_keyframe is not None and (
                index + 1 == len(ids) or shot.end_keyframe != ids[index + 1]
            ):
                raise ValueError("FLF must reference the immediate next approved keyframe")
        return self
