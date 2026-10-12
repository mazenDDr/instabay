"""FR-06, NFR-03: immutable recipes, byte checks and fake-first boundaries."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from instabay.core.recipe import RenderRecipe
from instabay.video.backends.stub import StubVideoBackend
from instabay.video.files import RenderError, digest, local_file
from instabay.video.keyframes import stub_recipe
from instabay.video.shotlist import FileRef, Keyframe, ShotList

ROOT = Path(__file__).parents[2]


def shotlist() -> ShotList:
    return ShotList.model_validate(
        {
            "reel_id": "synthetic-reel",
            "duration_s": 15,
            "shots": [
                {
                    "id": f"s{i}",
                    "role": "hook" if i == 0 else "cta" if i == 2 else "body",
                    "keyframe": {
                        "uri": "assets/keyframes/synthetic_mood.ppm",
                        "sha256": digest(ROOT / "assets/keyframes/synthetic_mood.ppm"),
                        "source": "synthetic",
                        "approved_by": "synthetic-fixture",
                        "approval_id": "synthetic-fixture-v1",
                        "faces_checked": True,
                        "attribution": "Abstract offline test pattern; no property depicted",
                    },
                    "motion_prompt": "Modest motion in abstract light, no facilities or people",
                    "negative_prompt": "facilities, rooms, faces, text, logos",
                    "camera": "push_in",
                    "seconds": 5,
                    "overlay": {"en": "A moment of calm.", "ar": "لحظة هدوء."},
                }
                for i in range(3)
            ],
        }
    )


def test_hash_changes_for_seed_and_every_input() -> None:
    recipe = stub_recipe(shotlist(), ROOT)
    assert (
        recipe.recipe_hash == RenderRecipe.model_validate_json(recipe.model_dump_json()).recipe_hash
    )
    data = recipe.model_dump(mode="json")
    data["motion"]["seeds"][0] += 1
    assert RenderRecipe.model_validate(data).recipe_hash != recipe.recipe_hash
    assert not recipe.generated and recipe.reference_only


def test_generated_facility_is_rejected() -> None:
    data = shotlist().shots[0].keyframe.model_dump()
    with pytest.raises(ValidationError, match="Facility"):
        Keyframe.model_validate(
            data | {"source": "generated", "scene": "facility", "prompt": "room", "seed": 7}
        )


@pytest.mark.parametrize("uri", ["../secret", "/tmp/file", "https://host/file", "assets//file"])
def test_file_path_cannot_escape(uri: str) -> None:
    with pytest.raises(ValidationError):
        FileRef(uri=uri, sha256="0" * 64)


def test_changed_source_and_symlink_escape_fail(tmp_path: Path) -> None:
    original = tmp_path / "a"
    original.write_text("a")
    ref = FileRef(uri="a", sha256=digest(original))
    original.write_text("b")
    with pytest.raises(RenderError):
        local_file(tmp_path, ref)
    (tmp_path / "escape").symlink_to(ROOT / "pyproject.toml")
    with pytest.raises(RenderError):
        local_file(tmp_path, FileRef(uri="escape", sha256=digest(ROOT / "pyproject.toml")))


def test_flf_must_reference_next_and_backend_capability() -> None:
    data = shotlist().model_dump()
    data["shots"][0]["end_keyframe"] = "s2"
    with pytest.raises(ValidationError, match="immediate"):
        ShotList.model_validate(data)
    data["shots"][0]["end_keyframe"] = "s1"
    with pytest.raises(ValidationError, match="unsupported FLF"):
        stub_recipe(ShotList.model_validate(data), ROOT)
    assert not StubVideoBackend().capabilities().flf2v
