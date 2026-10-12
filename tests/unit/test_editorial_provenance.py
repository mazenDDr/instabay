"""NFR-03: each generated motion shot remains bound to its own photographed evidence."""

import json
from pathlib import Path

import pytest

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import canonical_hash
from instabay.video.backends.base import ShotRecipe
from instabay.video.backends.editorial import EditorialVideoBackend
from instabay.video.files import RenderError, digest
from instabay.video.keyframes import stub_recipe
from tests.unit.test_video_recipe import ROOT, shotlist


@pytest.mark.parametrize(
    "defect", ["none", "conditioning", "undisclosed", "synthetic", "short", "bytes"]
)
def test_generated_shot_cannot_borrow_other_crop_or_fixture_approval(
    tmp_path: Path, monkeypatch, defect: str
) -> None:
    native = {
        "spec": {
            "image_sha256": "0" * 64
            if defect == "conditioning"
            else shotlist().shots[0].keyframe.sha256
        },
        "ai_disclosure": defect != "undisclosed",
        "reference_only": True,
    }
    motion = tmp_path / "motion.json"
    motion.write_text(json.dumps(native))
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"offline fixture video")
    data = stub_recipe(shotlist(), ROOT).model_dump()
    shot = data["shots"]["shots"][0]
    shot["keyframe"]["source"] = "synthetic" if defect == "synthetic" else "photo"
    shot["source_clip"] = {
        "uri": clip.name,
        "sha256": digest(clip),
        "generated": True,
        "credit": "fixture",
        "motion_recipe": {"uri": motion.name, "sha256": digest(motion)},
        "motion_recipe_hash": canonical_hash(native),
        "start_s": 0.5,
    }
    recipe = RenderRecipe.model_validate(data)
    assert recipe.generated and recipe.reference_only
    monkeypatch.setattr(
        "instabay.video.backends.editorial.probe",
        lambda _: {"format": {"duration": 5 if defect == "short" else 6}},
    )
    if defect == "bytes":
        clip.write_bytes(b"changed")
    backend = EditorialVideoBackend()
    if defect == "none":
        assert backend.render_shot(
            ShotRecipe(recipe=recipe, index=0), tmp_path, tmp_path
        ).file == str(clip)
    else:
        with pytest.raises(RenderError):
            backend.render_shot(ShotRecipe(recipe=recipe, index=0), tmp_path, tmp_path)
