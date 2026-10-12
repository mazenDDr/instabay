"""FR-06: long, complete scene shots replace the rejected detail/snapshot presets."""

import json

import pytest
from pydantic import ValidationError

from instabay.core.schemas import canonical_hash
from instabay.video.direction import (
    ScenicIntent,
    VideoBoard,
    resolve_object,
    schedule_intent,
)
from tests.unit.test_content_evidence import ROOT, campaign, selection


def scenic():
    path = ROOT / "tests/fixtures/llm/video_director__reference-w42-wed-1.json"
    return ScenicIntent.model_validate(json.loads(path.read_text())["response"])


def test_scenic_scene_hold_and_empty_hook_do_not_require_rapid_cuts():
    _, _, objects, slots = campaign()
    plan = schedule_intent(scenic())
    brief = selection(slots[2]).brief
    board = VideoBoard(brief=brief, brief_hash=canonical_hash(brief), plan=plan, catalog=objects)
    assert [b.frames for b in board.plan.beats] == [150] * 3
    assert board.plan.edit_style == "scenic" and not board.plan.beats[0].overlay.en
    assert sum(b.frames for b in board.plan.beats) == 450
    raw = plan.model_dump()
    raw["beats"][0]["frames"] = 60
    raw["beats"][1]["frames"] += 45
    raw["beats"][2]["frames"] += 45
    with pytest.raises(ValidationError, match="held for at least four"):
        type(plan).model_validate(raw)


def test_scenic_director_cannot_return_photographic_snapshots_or_opening_text():
    raw = scenic().model_dump()
    raw["beats"][1]["action"] = "photo_camera"
    with pytest.raises(ValidationError, match="Scenic shots"):
        ScenicIntent.model_validate(raw)
    raw = scenic().model_dump()
    raw["beats"][0]["overlay"] = {"en": "A panel", "ar": "لوحة"}
    with pytest.raises(ValidationError, match="empty overlays"):
        ScenicIntent.model_validate(raw)


def test_scene_crops_retain_place_features_and_reject_tiny_upscaled_details(tmp_path):
    _, _, objects, _ = campaign()
    obj = objects.get("shoreline")
    with pytest.raises(ValueError, match="full-resolution"):
        resolve_object(
            obj.model_copy(
                update={"crop": obj.crop.model_copy(update={"width": 400, "height": 700})}
            ),
            ROOT,
            ROOT / "outputs/test-no-write",
        )
    with pytest.raises(ValueError, match="context"):
        resolve_object(
            obj.model_copy(update={"crop": obj.crop.model_copy(update={"x": 500})}),
            ROOT,
            ROOT / "outputs/test-no-write",
        )
    raw = obj.model_dump()
    raw["reference_only"] = False
    with pytest.raises(ValidationError, match="production property"):
        type(obj).model_validate(raw)


def test_director_editor_removes_model_panels_and_rejects_repeated_scenes(tmp_path):
    from instabay.adapters.fake_llm import FakeLLM
    from instabay.agents.video_director import VideoDirector
    from instabay.db import SQLiteCallStore
    from instabay.llm import LLMOutputError, LLMService

    _, _, objects, slots = campaign()
    raw = json.loads(
        (ROOT / "tests/fixtures/llm/video_director__reference-w42-wed-1.json").read_text()
    )
    raw["response"]["beats"][0]["overlay"] = {"en": "Unwanted panel", "ar": "لوحة"}
    raw["response"]["beats"][-1]["role"] = "payoff"
    path = tmp_path / "video_director__reference-w42-wed-1.json"
    path.write_text(json.dumps(raw))
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        director = VideoDirector(LLMService(FakeLLM(tmp_path), store))
        board = director.direct(slots[2].id, selection(slots[2]).brief, objects)
        assert all(not b.overlay.en and not b.overlay.ar for b in board.plan.beats)
        assert board.plan.beats[-1].role == "cta"
    raw["response"]["beats"][1]["object_id"] = raw["response"]["beats"][0]["object_id"]
    path.write_text(json.dumps(raw))
    with SQLiteCallStore(tmp_path / "invalid.sqlite") as store:
        with pytest.raises(LLMOutputError):
            VideoDirector(LLMService(FakeLLM(tmp_path), store)).direct(
                slots[2].id, selection(slots[2]).brief, objects
            )
        assert all(c.status == "invalid_output" for c in store.calls())


def test_scenic_editor_rotates_identical_order_for_second_film(tmp_path):
    from instabay.adapters.fake_llm import FakeLLM
    from instabay.agents.video_director import VideoDirector
    from instabay.db import SQLiteCallStore
    from instabay.llm import LLMService

    _, _, objects, slots = campaign()
    first_order = [b.object_id for b in scenic().beats]
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        director = VideoDirector(LLMService(FakeLLM(ROOT / "tests/fixtures/llm"), store))
        board = director.direct(slots[2].id, selection(slots[2]).brief, objects, [first_order])
        assert [b.object_id for b in board.plan.beats] == first_order[1:] + first_order[:1]
        assert board.plan.beats[0].role == "hook" and board.plan.beats[-1].role == "cta"
