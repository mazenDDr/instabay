"""FR-08: measure editorial defects and actual movement without inventing an appeal score."""

from itertools import pairwise
from pathlib import Path
from statistics import median

from pydantic import Field

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import Boundary
from instabay.video.direction import VideoBoard
from instabay.video.files import command, local_file


class MotionWindow(Boundary):
    """FR-06: automatically selected source interval; the user need not pick clip endpoints."""

    start_s: float
    seconds: float
    median_delta: float
    near_static_fraction: float


def motion_deltas(file: Path) -> list[float]:
    """FR-08: text-free source motion, normalized grayscale frame differences at 12fps."""
    raw = command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(file),
            "-vf",
            "fps=12,scale=32:56",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    size = 32 * 56
    frames = [raw[i : i + size] for i in range(0, len(raw), size)]
    return [
        sum(abs(a - b) for a, b in zip(first, last, strict=True)) / (size * 255)
        for first, last in pairwise(frames)
    ]


def strongest_window(file: Path, seconds: float) -> MotionWindow:
    """FR-06: median avoids selecting a lone flash as a hook; geometry review stays separate."""
    changes = motion_deltas(file)
    count = max(1, round(seconds * 12) - 1)
    if len(changes) < count:
        raise ValueError("Footage is shorter than the requested edit")
    start = max(
        range(len(changes) - count + 1),
        key=lambda i: (
            median(changes[i : i + count]),
            -sum(d < 0.001 for d in changes[i : i + count]),
        ),
    )
    selected = changes[start : start + count]
    return MotionWindow(
        start_s=start / 12,
        seconds=seconds,
        median_delta=median(selected),
        near_static_fraction=sum(d < 0.001 for d in selected) / len(selected),
    )


class CreativeReport(Boundary):
    """FR-08: observable film checks; retention, beauty and property fidelity require labels."""

    first_visual_change_s: float
    shot_count: int
    distinct_subjects: int
    unique_source_photos: int
    unique_motion_clips: int
    repeated_clip_count: int
    text_fraction: float
    has_audio: bool
    motion: list[MotionWindow]
    flags: list[str] = Field(default_factory=list)
    human_appeal_review: str = "pending"
    engagement_lift: float | None = None


def creative_report(board: VideoBoard, recipe: RenderRecipe, root: Path) -> CreativeReport:
    """FR-08: separate edit completeness, technical quality and unmeasured audience response."""
    shots = recipe.shots.shots
    clips = [s.source_clip for s in shots if s.source_clip]
    motion = []
    flags = []
    for shot in shots:
        if shot.source_clip:
            changes = motion_deltas(local_file(root, shot.source_clip))
            start = round(shot.source_clip.start_s * 12)
            selected = changes[start : start + max(1, round(shot.seconds * 12) - 1)]
            if not selected:
                flags.append("Missing decoded movement evidence")
                continue
            window = MotionWindow(
                start_s=shot.source_clip.start_s,
                seconds=shot.seconds,
                median_delta=median(selected),
                near_static_fraction=sum(d < 0.001 for d in selected) / len(selected),
            )
            motion.append(window)
            # Working heuristic, not an engagement or semantic-quality threshold.
            if window.near_static_fraction > 0.8:
                flags.append(f"{shot.id}: physical motion is nearly static; inspect or replace")
    if len(clips) < 2:
        flags.append("Two distinct physical-motion subjects are not yet available")
    unique = len({c.sha256 for c in clips})
    if unique < len(clips):
        flags.append("A motion clip repeats without a new visual purpose")
    audio = bool(recipe.shots.audio.music or recipe.shots.audio.voiceover)
    if not audio:
        flags.append("Sound direction has no actual audio track")
    text_seconds = sum(
        (s.text_end_s if s.text_end_s is not None else s.seconds) - s.text_start_s
        for s in shots
        if s.overlay.en or s.overlay.ar
    )
    return CreativeReport(
        first_visual_change_s=shots[0].seconds,
        shot_count=len(shots),
        distinct_subjects=len({b.object_id for b in board.plan.beats}),
        unique_source_photos=len(
            {board.catalog.get(b.object_id).photo.sha256 for b in board.plan.beats}
        ),
        unique_motion_clips=unique,
        repeated_clip_count=len(clips) - unique,
        text_fraction=text_seconds / recipe.shots.duration_s,
        has_audio=audio,
        motion=motion,
        flags=flags,
    )
