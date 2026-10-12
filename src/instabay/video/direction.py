"""FR-06: brief-led direction grounded in a catalog of observed resort objects."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from instabay.core.schemas import Boundary, Brief, Hash, Identifier, canonical_hash
from instabay.video.files import command, digest, local_file
from instabay.video.shotlist import FileRef, Keyframe, Overlay, Shot, ShotList, SourceClip


class CropBox(Boundary):
    """NFR-04: observed pixels, not a requested invented view of the property."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ResortObject(Boundary):
    """FR-08: evidence, crop approval and rights are supplied by the catalog, never an LLM."""

    id: Identifier
    label: str
    observed: str
    photo: FileRef
    crop: CropBox
    approved_by: str
    approval_id: str
    faces_checked: Literal[True]
    attribution: str
    author: str
    license_id: str
    source_page: str
    license_url: str
    reference_only: bool = True
    source: Literal["photo", "synthetic"] = "photo"
    clip: SourceClip | None = None
    allowed_actions: tuple[
        Literal["photo_camera", "water_ripples", "plant_sway", "recorded_footage"], ...
    ] = ("photo_camera",)


class ObjectCatalog(Boundary):
    """FR-06: the director selects objects, while a resolver handles physical references."""

    resort: str
    objects: list[ResortObject] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({o.id for o in self.objects}) != len(self.objects):
            raise ValueError("Object IDs must be unique")
        return self

    def get(self, object_id: str) -> ResortObject:
        for item in self.objects:
            if item.id == object_id:
                return item
        raise ValueError("Director requested an object absent from the evidence catalog")


class StoryBeat(Boundary):
    """FR-06: visual purpose, action and edit timing, instead of human-specified end frames."""

    id: Identifier
    object_id: Identifier
    role: Literal["hook", "detail", "reveal", "payoff", "cta"]
    frames: int = Field(ge=20, le=120)
    purpose: str = Field(min_length=1, max_length=300)
    brief_anchor: Literal["hook", "angle", "key_message", "visual_description", "cta"]
    camera: Literal["push_in", "pull_out", "pan_left", "pan_right", "static"]
    action: Literal["photo_camera", "water_ripples", "plant_sway", "recorded_footage"]
    action_prompt: str = Field(min_length=1, max_length=800)
    overlay: Overlay
    text_position: Literal["upper", "lower"] = "lower"


class BeatIntent(Boundary):
    """FR-06: the LLM directs subject/action/purpose; the editor computes exact frame counts."""

    id: Identifier
    object_id: Identifier
    role: Literal["hook", "detail", "reveal", "payoff", "cta"]
    pace: Literal["quick", "steady", "linger"] = "steady"
    purpose: str = Field(min_length=1, max_length=300)
    brief_anchor: Literal["hook", "angle", "key_message", "visual_description", "cta"]
    camera: Literal["push_in", "pull_out", "pan_left", "pan_right", "static"]
    action: Literal["photo_camera", "water_ripples", "plant_sway", "recorded_footage"]
    action_prompt: str = Field(min_length=1, max_length=800)
    overlay: Overlay
    text_position: Literal["upper", "lower"] = "lower"


class CreativeIntent(Boundary):
    """FR-06: semantic direction without asking an LLM or a user to do timeline arithmetic."""

    reel_id: Identifier
    idea: str = Field(min_length=1, max_length=500)
    viewer_payoff: str = Field(min_length=1, max_length=300)
    hook_mechanism: str = Field(min_length=1, max_length=300)
    bpm: int = Field(default=90, ge=60, le=140)
    missing_visuals: list[str] = Field(default_factory=list)
    beats: list[BeatIntent] = Field(min_length=6, max_length=10)


class CreativePlan(Boundary):
    """FR-06: one idea, visible hook, emotional payoff and one brief-aligned CTA."""

    reel_id: Identifier
    idea: str = Field(min_length=1, max_length=500)
    viewer_payoff: str = Field(min_length=1, max_length=300)
    hook_mechanism: str = Field(min_length=1, max_length=300)
    bpm: int = Field(default=90, ge=60, le=140)
    missing_visuals: list[str] = Field(default_factory=list)
    beats: list[StoryBeat] = Field(min_length=6, max_length=10)

    @model_validator(mode="after")
    def narrative(self) -> Self:
        if self.beats[0].role != "hook" or self.beats[-1].role != "cta":
            raise ValueError("Hook must open the film; brief CTA must close it")
        frames = sum(b.frames for b in self.beats)
        if not 450 <= frames <= 900 or frames % 30:
            raise ValueError("The edit must last a whole 15-30 seconds at 30fps")
        if len({b.id for b in self.beats}) != len(self.beats):
            raise ValueError("Beat IDs must be unique")
        if self.beats[0].frames > 60:
            raise ValueError("The opening visual must change within two seconds")
        if len({b.object_id for b in self.beats}) < 3:
            raise ValueError("The film needs at least three observed subjects")
        if not any(b.role == "reveal" for b in self.beats):
            raise ValueError("A detail-first film must deliver a wider reveal")
        if self.beats[0].brief_anchor != "hook" or self.beats[-1].brief_anchor != "cta":
            raise ValueError("Hook and CTA must explicitly serve the brief")
        if sum(b.frames for b in self.beats if b.overlay.en or b.overlay.ar) > frames * 0.5:
            raise ValueError("Let the resort carry the story: text occupies at most half the film")
        for beat in self.beats:
            if not all(
                len(t) <= 45 and len(t.split()) <= 7 for t in [beat.overlay.en, beat.overlay.ar]
            ):
                raise ValueError("On-screen copy must be a short thought, not a caption paragraph")
            if bool(beat.overlay.en) != bool(beat.overlay.ar):
                raise ValueError("Each text beat needs independently written EN and AR versions")
        return self


class VideoBoard(Boundary):
    """NFR-03: bind creative decisions to the exact brief and immutable source evidence."""

    brief: Brief
    brief_hash: Hash
    plan: CreativePlan
    catalog: ObjectCatalog

    @model_validator(mode="after")
    def grounded(self) -> Self:
        if canonical_hash(self.brief) != self.brief_hash:
            raise ValueError("The storyboard does not belong to this brief")
        if self.plan.missing_visuals:
            raise ValueError("Obtain the missing real media before rendering this concept")
        for beat in self.plan.beats:
            item = self.catalog.get(beat.object_id)
            if beat.action not in item.allowed_actions:
                raise ValueError("Requested action does not match the observed physical object")
        active = {b.object_id for b in self.plan.beats if b.action != "photo_camera"}
        if self.plan.beats[0].action == "photo_camera" or len(active) < 2:
            raise ValueError("Open with physical movement and stage two distinct active subjects")
        if "question" in self.brief.hook.lower() and not (
            self.plan.beats[0].overlay.en.endswith("?")
            and self.plan.beats[0].overlay.ar.endswith(("؟", "?"))
        ):
            raise ValueError("The directed hook must preserve the brief's question style")
        return self


def schedule_intent(intent: CreativeIntent, duration_s: int = 18) -> CreativePlan:
    """FR-06: frame-accurate constrained allocation; creative words never determine timing math."""
    target = duration_s * 30
    if not 450 <= target <= 900:
        raise ValueError("Edit duration must be 15-30 seconds")
    n = len(intent.beats)
    frames = [40] + [20] * (n - 1)
    weights = [{"quick": 40, "steady": 80, "linger": 100}[b.pace] for b in intent.beats[1:]]
    desired = [40.0] + [(target - 40) * w / sum(weights) for w in weights]
    while sum(frames) < target:
        candidates = [i for i in range(1, n) if frames[i] < 120]
        if not candidates:
            raise ValueError("Add more meaningful beats for this duration")
        i = max(candidates, key=lambda k: desired[k] - frames[k])
        frames[i] += min(10, target - sum(frames))
    data = intent.model_dump(exclude={"beats"})
    data["beats"] = [
        b.model_dump(exclude={"pace"}) | {"frames": f}
        for b, f in zip(intent.beats, frames, strict=True)
    ]
    return CreativePlan.model_validate(data)


def resolve_object(item: ResortObject, root: Path, directory: Path) -> Keyframe:
    """FR-06: automatically prepare a conditioning crop; no user frame sequencing."""
    from PIL import Image

    root, directory = root.resolve(), directory.resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Resolved media must stay under the recipe root")
    source = local_file(root, item.photo)
    with Image.open(source) as image:
        if (
            item.crop.x + item.crop.width > image.width
            or item.crop.y + item.crop.height > image.height
        ):
            raise ValueError("Observed crop exceeds the source photograph")
    output = directory / f"{item.id}.pending.jpg"
    directory.mkdir(parents=True, exist_ok=True)
    c = item.crop
    command(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"crop={c.width}:{c.height}:{c.x}:{c.y},scale=576:1024:force_original_aspect_ratio=increase,crop=576:1024",
            "-frames:v",
            "1",
            str(output),
        ]
    )
    sha = digest(output)
    immutable = directory / f"{item.id}-{sha}.jpg"
    output.replace(immutable)
    return Keyframe(
        uri=immutable.relative_to(root.resolve()).as_posix(),
        sha256=sha,
        source=item.source,
        scene="mood",
        approved_by=item.approved_by,
        approval_id=item.approval_id,
        faces_checked=True,
        attribution=item.attribution,
        reference_only=item.reference_only,
    )


def compile_board(
    board: VideoBoard, root: Path, directory: Path, *, animatic: bool = False
) -> ShotList:
    """FR-06: schedule distinct meaningful shots; missing motion never silently becomes a still."""
    refs = {
        oid: resolve_object(board.catalog.get(oid), root, directory)
        for oid in {b.object_id for b in board.plan.beats}
    }
    if len({r.sha256 for r in refs.values()}) < 3:
        raise ValueError("Three renamed copies of one visual are not shot variety")
    shots = []
    used_clips: set[str] = set()
    for beat in board.plan.beats:
        item = board.catalog.get(beat.object_id)
        motion = beat.action != "photo_camera"
        if motion and not item.clip and not animatic:
            raise ValueError(
                f"Object {item.id} needs {beat.action} footage; "
                "request media or explicitly render an animatic"
            )
        clip = item.clip if motion and not animatic else None
        if clip:
            if clip.sha256 in used_clips:
                raise ValueError("Reusing an identical clip is not a new directed shot")
            used_clips.add(clip.sha256)
        duration = beat.frames / 30
        shots.append(
            Shot(
                id=beat.id,
                role="hook" if beat.role == "hook" else "cta" if beat.role == "cta" else "body",
                keyframe=refs[item.id],
                source_clip=clip,
                seconds=duration,
                camera=beat.camera if not clip else "static",
                motion_strength=0.16,
                motion_prompt=beat.action_prompt,
                negative_prompt=(
                    Path(__file__).parents[1] / "prompts/video_negative.md"
                ).read_text(),
                overlay=beat.overlay,
                text_position=beat.text_position,
                text_start_s=0.1,
                text_end_s=min(duration - 0.1, 1.8),
            )
        )
    return ShotList(
        reel_id=board.plan.reel_id,
        duration_s=sum(b.frames for b in board.plan.beats) // 30,
        shots=shots,
    )
