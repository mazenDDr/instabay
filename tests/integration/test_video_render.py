"""FR-07, NFR-03: actual offline MP4, cache and Arabic overlay acceptance."""

import sqlite3
from pathlib import Path

import pytest

from instabay.video.backends.stub import StubVideoBackend
from instabay.video.files import RenderError
from instabay.video.keyframes import stub_recipe
from instabay.video.post import shape_arabic
from instabay.video.studio import VideoStudio
from tests.unit.test_video_recipe import ROOT, shotlist


class CountingStub(StubVideoBackend):
    calls = 0

    def render_shot(self, *args, **kwargs):
        self.calls += 1
        return super().render_shot(*args, **kwargs)


def test_actual_stub_reel_specs_arabic_and_cache_survive_restart(tmp_path: Path) -> None:
    recipe = stub_recipe(shotlist(), ROOT, preset="ultrafast")
    backend = CountingStub()
    studio = VideoStudio(tmp_path / "state.sqlite", ROOT, tmp_path / "renders", backend)
    result = studio.render(recipe)
    assert backend.calls == 3
    assert result.qa.spec_ok and result.qa.moov_at_front
    assert (result.qa.width, result.qa.height, result.qa.fps) == (1080, 1920, 30)
    assert len(result.frame_hashes) == 450
    assert result.qa.status == "needs_review" and result.qa.visual is None
    assert not result.ai_disclosure and result.reference_only
    assert shape_arabic("لحظة هدوء.") != "لحظة هدوء."
    with sqlite3.connect(tmp_path / "state.sqlite") as conn:
        row = conn.execute("SELECT recipe_hash,status,recipe_json FROM render_job").fetchone()
        assert row[0] == recipe.recipe_hash and row[1] == "complete"
        assert row[2] == recipe.model_dump_json()
    cached = VideoStudio(tmp_path / "state.sqlite", ROOT, tmp_path / "renders", backend).render(
        recipe
    )
    assert cached == result and backend.calls == 3
    manifest = Path(result.file).parent / "result.json"
    original = manifest.read_bytes()
    changed = result.model_dump()
    changed["qa"]["status"] = "passed"
    from instabay.video.studio import RenderResult

    manifest.write_text(RenderResult.model_validate(changed).model_dump_json())
    with pytest.raises(RenderError, match="metadata"):
        studio.render(recipe)
    manifest.write_bytes(original)
    Path(result.file).write_bytes(b"corrupted")
    with pytest.raises(RenderError, match="Cached"):
        studio.render(recipe)
    assert backend.calls == 3
