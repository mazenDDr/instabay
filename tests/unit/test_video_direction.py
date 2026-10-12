"""FR-06, FR-08: brief fidelity, editorial constraints and media provenance defects."""

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from instabay.core.schemas import Brief, canonical_hash
from instabay.video.direction import (
    CreativeIntent,
    ObjectCatalog,
    VideoBoard,
    compile_board,
    schedule_intent,
)
from instabay.video.shotlist import SourceClip

ROOT = Path(__file__).parents[2]


def intent() -> CreativeIntent:
    fixture = json.loads(
        (ROOT / "tests/fixtures/llm/video_director__2026-w42-sun-1.json").read_text()
    )
    return CreativeIntent.model_validate(fixture["response"])


def catalog() -> ObjectCatalog:
    return ObjectCatalog.model_validate(
        yaml.safe_load((ROOT / "config/resort-objects.yaml").read_text())
    )


def brief() -> Brief:
    path = ROOT / "tests/fixtures/llm/brief_writer__2026-w42-sun-1.json"
    return Brief.model_validate(json.loads(path.read_text())["response"])


def board() -> VideoBoard:
    shared = brief()
    return VideoBoard(
        brief=shared,
        brief_hash=canonical_hash(shared),
        plan=schedule_intent(intent()),
        catalog=catalog(),
    )


@pytest.mark.parametrize("seconds", [15, 18, 24, 28])
def test_code_schedules_exact_frames_without_llm_arithmetic(seconds: int) -> None:
    plan = schedule_intent(intent(), seconds)
    assert sum(b.frames for b in plan.beats) == seconds * 30
    assert plan.beats[0].frames == 40
    assert all(20 <= b.frames <= 120 for b in plan.beats)
    assert "frames" not in intent().beats[0].model_dump()
    with pytest.raises(ValueError, match="more meaningful beats"):
        schedule_intent(intent(), 30)  # Eight short shots cannot cover 30s without excessive holds.


@pytest.mark.parametrize(
    "defect", ["brief", "unknown", "unsupported", "still", "question", "missing"]
)
def test_director_cannot_replace_brief_or_invent_motion(defect: str) -> None:
    data = board().model_dump()
    if defect == "brief":
        data["brief"]["key_message"] = "invented spa"
    elif defect == "unknown":
        data["plan"]["beats"][1]["object_id"] = "spa"
    elif defect == "unsupported":
        data["plan"]["beats"][3]["action"] = "water_ripples"
    elif defect == "still":
        data["plan"]["beats"][0]["action"] = "photo_camera"
    elif defect == "question":
        data["plan"]["beats"][0]["overlay"]["en"] = "A slow escape."
    else:
        data["plan"]["missing_visuals"] = ["licensed spa footage"]
    with pytest.raises(ValidationError):
        VideoBoard.model_validate(data)


@pytest.mark.parametrize("defect", ["late_hook", "paragraph", "text_wall"])
def test_edit_constraints_reject_old_video_defects(defect: str) -> None:
    data = board().model_dump()
    beats = data["plan"]["beats"]
    if defect == "late_hook":
        beats[0]["frames"] += 30
        beats[1]["frames"] -= 30
    elif defect == "paragraph":
        beats[0]["overlay"]["en"] = "This is a long paragraph that covers the actual resort scene."
    else:
        for beat in beats:
            beat["overlay"] = {"en": "Resort", "ar": "منتجع"}
    with pytest.raises(ValidationError):
        VideoBoard.model_validate(data)


def test_missing_motion_requires_explicit_animatic(tmp_path: Path, monkeypatch) -> None:
    from instabay.video.shotlist import Keyframe

    def resolve(item, *args):
        return Keyframe(
            uri=f"{item.id}.jpg",
            sha256=canonical_hash(item.id),
            source="photo",
            approved_by="test-human",
            approval_id="test-crop",
            faces_checked=True,
            attribution="offline fixture",
            reference_only=True,
        )

    monkeypatch.setattr("instabay.video.direction.resolve_object", resolve)
    with pytest.raises(ValueError, match="needs plant_sway footage"):
        compile_board(board(), tmp_path, tmp_path)
    animatic = compile_board(board(), tmp_path, tmp_path, animatic=True)
    assert len(animatic.shots) == 8 and animatic.duration_s == 18
    assert all(s.source_clip is None and s.end_keyframe is None for s in animatic.shots)
    data = board().model_dump()
    for item in data["catalog"]["objects"]:
        if item["id"] in {"flowers", "water"}:
            item["clip"] = SourceClip(
                uri="same.mp4", sha256="a" * 64, generated=False, credit="offline"
            ).model_dump()
    with pytest.raises(ValueError, match="identical clip"):
        compile_board(VideoBoard.model_validate(data), tmp_path, tmp_path)
    monkeypatch.setattr(
        "instabay.video.direction.resolve_object",
        lambda item, *args: resolve(item).model_copy(update={"sha256": "b" * 64}),
    )
    with pytest.raises(ValueError, match="renamed copies"):
        compile_board(board(), tmp_path, tmp_path, animatic=True)


def test_motion_window_uses_sustained_change_not_one_flash(tmp_path: Path, monkeypatch) -> None:
    from instabay.video.creative_qa import strongest_window

    monkeypatch.setattr(
        "instabay.video.creative_qa.motion_deltas", lambda _: [0.8] + [0.0] * 14 + [0.01] * 15
    )
    window = strongest_window(tmp_path / "clip.mp4", 1)
    assert window.start_s >= 15 / 12 and window.median_delta == 0.01
    assert window.near_static_fraction == 0
