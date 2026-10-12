"""FR-01, FR-09: the Generate week button freezes the brand, swaps the GPU and always swaps back."""

from datetime import date
from pathlib import Path

import pytest

from instabay.adapters.fake_llm import FakeLLM
from instabay.assets.library import AssetLibrary
from instabay.dashboard.jobs import Generator, next_monday
from instabay.repository import Repository
from tests.support import demo_brand
from tests.unit.test_assets import PILLARS, owner_photo


class FakeGpu:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def caption_up(self) -> str:
        self.calls.append("up")
        return "http://127.0.0.1:18765"

    def caption_down(self) -> None:
        self.calls.append("down")


def test_job_freezes_brand_swaps_gpu_and_reports_failures(tmp_path: Path) -> None:
    with AssetLibrary(tmp_path / "ws", root=tmp_path) as library:
        for index, pillar in enumerate(PILLARS):
            owner_photo(library, 70 + index, pillar)
    gpu = FakeGpu()
    generator = Generator(
        root=tmp_path,
        runs=tmp_path / "outputs" / "studio",
        workspace=tmp_path / "ws",
        brand=demo_brand(),
        gpu=gpu,
        client_factory=lambda origin: FakeLLM(Path("tests/fixtures/llm").resolve()),
    )
    status = generator.start("Owner", date(2026, 10, 19), wait=True)
    status = generator.current()
    assert status is not None and status.state == "failed"
    assert [s.state for s in status.steps] == ["done", "done", "done", "failed", "done"]
    assert gpu.calls == ["up", "down"]
    assert "5 ready photos" in status.steps[0].detail
    repository = Repository(tmp_path / "outputs" / "studio" / "week-2026-10-19" / "posts.sqlite")
    from instabay.core.schemas import canonical_hash

    assert repository.frozen_brand(canonical_hash(demo_brand())) == demo_brand()
    repository.close()
    assert (tmp_path / "outputs" / "studio" / "jobs" / "latest.json").exists()
    with pytest.raises(ValueError, match="Monday"):
        generator.start("Owner", date(2026, 10, 20))


def test_job_without_ready_photos_never_touches_the_gpu(tmp_path: Path) -> None:
    gpu = FakeGpu()
    generator = Generator(
        root=tmp_path,
        runs=tmp_path / "outputs" / "studio",
        workspace=tmp_path / "ws",
        brand=demo_brand(),
        gpu=gpu,
        client_factory=lambda origin: FakeLLM(Path("tests/fixtures/llm").resolve()),
    )
    generator.start("Owner", next_monday(date(2026, 10, 13)), wait=True)
    status = generator.current()
    assert status is not None and status.state == "failed" and gpu.calls == []
    assert "No usable photos" in (status.error or "")
