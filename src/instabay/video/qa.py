"""FR-07, FR-08: actual spec checks; missing semantic/continuity evidence flags a reel."""

import struct
from fractions import Fraction
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import Boundary
from instabay.video.files import RenderError, binary, command, probe


class VisualEvidence(Boundary):
    """FR-08: native visual judgments must be measured, not placeholder numbers."""

    provider: str
    synthetic: bool
    seam_similarity: list[float] = Field(default_factory=list)
    subject_consistency: float = Field(ge=0, le=1)
    background_consistency: float = Field(ge=0, le=1)
    palette_distance: float = Field(ge=0, le=1)
    planned_scene: bool
    distorted_faces_or_hands: bool
    stray_text: bool
    consistency_scope: Literal["whole_reel", "within_shots"] = "whole_reel"
    editorial_brief_match: bool | None = None
    object_actions_readable: bool | None = None


class VisualQA(Protocol):
    """NFR-05: HUMAN runs pinned DINO/Qwen-VL adapters; CI supplies fixture evidence."""

    def evaluate(self, file: Path, recipe: RenderRecipe) -> VisualEvidence: ...


class VideoQA(Boundary):
    """FR-07: spec success alone never implies semantic or property fidelity."""

    spec_ok: bool
    width: int
    height: int
    fps: float
    duration_s: float
    size_bytes: int
    moov_at_front: bool
    violations: list[str]
    flicker: float | None = None
    visual: VisualEvidence | None = None
    status: Literal["passed", "needs_review", "failed"]


def faststart(file: Path) -> bool:
    """FR-07: parse top-level MP4 atoms instead of searching payload text."""
    with file.open("rb") as stream:
        seen_moov = False
        total = file.stat().st_size
        while stream.tell() + 8 <= total:
            offset = stream.tell()
            size, kind = struct.unpack(">I4s", stream.read(8))
            header = 8
            if size == 1:
                size = struct.unpack(">Q", stream.read(8))[0]
                header = 16
            if size == 0:
                size = total - offset
            if size < header or offset + size > total:
                return False
            if kind == b"moov":
                seen_moov = True
            if kind == b"mdat":
                return seen_moov
            stream.seek(offset + size)
    return False


def check_spec(file: Path, recipe: RenderRecipe) -> VideoQA:
    """FR-07: verify actual H.264/yuv420p/30fps/1080x1920/AAC/48kHz/size/duration."""
    data = probe(file)
    videos = [s for s in data["streams"] if s.get("codec_type") == "video"]
    audios = [s for s in data["streams"] if s.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise RenderError("Reel needs exactly one video and one audio stream")
    video, audio = videos[0], audios[0]
    width, height = int(video["width"]), int(video["height"])
    fps = float(Fraction(video["avg_frame_rate"]))
    duration = float(data["format"]["duration"])
    front = faststart(file)
    checks = {
        "video codec": video.get("codec_name") == "h264",
        "pixel format": video.get("pix_fmt") == "yuv420p",
        "resolution": (width, height) == (1080, 1920),
        "frame rate": fps == 30 and float(Fraction(video["r_frame_rate"])) == 30,
        "duration": abs(duration - recipe.shots.duration_s) <= 0.1,
        "video timing": abs(float(video.get("duration", 0)) - recipe.shots.duration_s) <= 1 / 30,
        "audio codec": audio.get("codec_name") == "aac",
        "sample rate": int(audio.get("sample_rate", 0)) == 48000,
        "size": file.stat().st_size <= recipe.post.max_bytes,
        "faststart": front,
    }
    violations = [key for key, valid in checks.items() if not valid]
    return VideoQA(
        spec_ok=not violations,
        width=width,
        height=height,
        fps=fps,
        duration_s=duration,
        size_bytes=file.stat().st_size,
        moov_at_front=front,
        violations=violations,
        status="failed" if violations else "needs_review",
    )


def evaluate(file: Path, recipe: RenderRecipe, visual: VisualQA | None = None) -> VideoQA:
    """FR-08: real low-resolution frame differences plus optional independent visual gate."""
    spec = check_spec(file, recipe)
    raw = command(
        [
            str(binary("ffmpeg")),
            "-v",
            "error",
            "-i",
            str(file),
            "-an",
            "-vf",
            "scale=32:56",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    frames = [raw[i : i + 1792] for i in range(0, len(raw), 1792)]
    cuts = set()
    elapsed = 0.0
    for shot in recipe.shots.shots[:-1]:
        elapsed += shot.seconds
        cuts.add(round(elapsed * 30))
    changes = [
        sum(abs(a - b) for a, b in zip(frames[i - 1], frame, strict=True)) / (1792 * 255)
        for i, frame in enumerate(frames)
        if i > 0 and i not in cuts
    ]
    flicker = sum(changes) / len(changes) if changes else None
    evidence = visual.evaluate(file, recipe) if visual else None
    violations = list(spec.violations)
    if flicker is None or flicker > recipe.post.flicker_threshold:
        violations.append("temporal difference exceeds configured threshold")
    if evidence is None:
        violations.append("semantic/subject/background/seam/palette QA pending")
    else:
        if recipe.generated and evidence.synthetic:
            violations.append("synthetic QA cannot validate native motion")
        if recipe.post.style == "editorial":
            if evidence.consistency_scope != "within_shots":
                violations.append("Within-shot consistency evidence pending")
            if (
                evidence.editorial_brief_match is not True
                or evidence.object_actions_readable is not True
            ):
                violations.append("Directed brief/action review pending or failed")
        elif len(evidence.seam_similarity) != len(recipe.shots.shots) - 1 or any(
            s < recipe.post.continuity_threshold for s in evidence.seam_similarity
        ):
            violations.append("DINO seam continuity failed")
        if (
            min(evidence.subject_consistency, evidence.background_consistency)
            < recipe.post.continuity_threshold
        ):
            violations.append("subject/background continuity failed")
        if not evidence.planned_scene or evidence.distorted_faces_or_hands or evidence.stray_text:
            violations.append("semantic QA failed")
        if evidence.palette_distance > 0.2:
            violations.append("brand palette QA failed")
    return VideoQA.model_validate(
        spec.model_dump()
        | {
            "flicker": flicker,
            "visual": evidence,
            "violations": violations,
            "status": "failed" if not spec.spec_ok else "needs_review" if violations else "passed",
        }
    )
