"""NFR-03: recorded GPU imports cannot hide changed bytes or incorrect crop provenance."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import canonical_hash
from instabay.video.backends.base import ShotRecipe
from instabay.video.backends.recorded import RecordedMotionBackend
from instabay.video.files import RenderError, digest
from instabay.video.keyframes import stub_recipe
from instabay.video.studio import VideoStudio
from tests.unit.test_video_recipe import ROOT, shotlist


def recorded(tmp_path: Path, *, disclosed: bool = True) -> RenderRecipe:
    native = {
        "spec": {"image_sha256": shotlist().shots[0].keyframe.sha256},
        "ai_disclosure": disclosed,
        "reference_only": True,
    }
    source = tmp_path / "motion.json"
    source.write_text(json.dumps(native))
    # Only boundary validation is tested: these are deliberately non-video bytes.
    clip = tmp_path / "recorded.mp4"
    clip.write_bytes(b"offline-test-clip-bytes")
    recipe = stub_recipe(shotlist(), ROOT).model_dump()
    recipe["post"]["recorded_motion"] = {
        "recipe": {"uri": source.name, "sha256": digest(source)},
        "recipe_hash": canonical_hash(native),
        "conditioning_sha256": native["spec"]["image_sha256"],
        "clips": [{"uri": clip.name, "sha256": digest(clip)}] * 3,
    }
    return RenderRecipe.model_validate(recipe)


@pytest.fixture
def local_work(tmp_path: Path) -> Path:
    return tmp_path


def test_recorded_identity_disclosure_and_bytes_are_verified(local_work: Path) -> None:
    recipe = recorded(local_work)
    assert recipe.generated and recipe.reference_only
    backend = RecordedMotionBackend()
    shot = ShotRecipe(recipe=recipe, index=0)
    result = backend.render_shot(shot, local_work, local_work)
    Path(result.file).write_bytes(b"changed")
    with pytest.raises(RenderError):
        backend.render_shot(shot, local_work, local_work)


def test_undisclosed_native_recording_is_rejected(local_work: Path) -> None:
    recipe = recorded(local_work, disclosed=False)
    with pytest.raises(RenderError, match="identity"):
        RecordedMotionBackend().render_shot(
            ShotRecipe(recipe=recipe, index=0), local_work, local_work
        )


def test_recorded_recipe_requires_conditioning_match_and_import_backend(local_work: Path) -> None:
    recipe = recorded(local_work)
    data = recipe.model_dump()
    data["post"]["recorded_motion"]["conditioning_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="conditioning"):
        RenderRecipe.model_validate(data)
    with pytest.raises(RenderError, match="recorded CPU"):
        VideoStudio(local_work / "state.sqlite", ROOT, local_work / "renders").render(recipe)
