"""NFR-03: measured CPU decoded-frame replay, two independent renders and no cache reuse."""

from pathlib import Path

import pytest

from instabay.video.keyframes import stub_recipe
from instabay.video.studio import VideoStudio
from tests.unit.test_video_recipe import ROOT, shotlist


@pytest.mark.determinism
def test_stub_frame_hashes_replay_on_this_runtime(tmp_path: Path) -> None:
    recipe = stub_recipe(shotlist(), ROOT, preset="ultrafast")
    first = VideoStudio(tmp_path / "a.sqlite", ROOT, tmp_path / "a").render(recipe)
    second = VideoStudio(tmp_path / "b.sqlite", ROOT, tmp_path / "b").render(recipe)
    assert len(first.frame_hashes) == 450 and first.frame_hashes == second.frame_hashes
