"""FR-01, FR-06, FR-09: autopilot and step-by-step weekly pipelines stop at owner approval."""

import time
from datetime import date
from pathlib import Path

from instabay.adapters.fake_llm import FakeLLM
from instabay.assets.library import AssetLibrary
from instabay.assets.variants import StubViewBackend
from instabay.core.schemas import canonical_hash
from instabay.dashboard.jobs import Pipeline
from instabay.repository import Repository
from tests.support import demo_brand
from tests.unit.test_assets import jpeg


class FakeService:
    def __init__(self) -> None:
        self.calls = 0

    def ensure(self) -> str:
        self.calls += 1
        return "http://127.0.0.1:18790"


def pipeline(tmp_path: Path) -> Pipeline:
    with AssetLibrary(tmp_path / "ws", root=tmp_path) as library:
        for n, pillar in enumerate(["underwater", "spa", "guests", "local", "offers", "spa"]):
            a = library.add(
                jpeg((n * 40, 90, 160), (1200, 1500)), added_by="Owner", rights_confirmed=True
            )
            library.review(a.id, owner_pillar=pillar)
    return Pipeline(
        root=tmp_path,
        runs=tmp_path / "outputs" / "studio",
        workspace=tmp_path / "ws",
        brand=demo_brand(),
        service=FakeService(),
        engine=None,
        judge=None,
        views=StubViewBackend(),
        view_revision="r",
        client_factory=lambda origin: FakeLLM(Path("tests/fixtures/llm").resolve()),
    )


def test_autopilot_plans_fills_gaps_freezes_and_reports_failures(tmp_path: Path) -> None:
    runner = pipeline(tmp_path)
    runner.start("Owner", date(2026, 10, 19), "autopilot", wait=True)
    status = runner.current()
    assert status is not None and status.state == "failed"
    states = {s.key: s.state for s in status.steps}
    assert states == {
        "sort": "done",
        "plan": "done",
        "shots": "done",
        "freeze": "done",
        "write": "failed",
    }
    assert status.new_shots, "6 photos cannot fill a 7-post week without new shots"
    with AssetLibrary(tmp_path / "ws", root=tmp_path) as library:
        shots = [library.get(i) for i in status.new_shots]
    # No d3 engine here, so no shot reached the 0.8 bar: autopilot hides them all.
    assert all(s.rejected and not s.approved for s in shots)
    repository = Repository(tmp_path / "outputs" / "studio" / "week-2026-10-19" / "posts.sqlite")
    assert repository.frozen_brand(canonical_hash(demo_brand())) == demo_brand()
    repository.close()


def test_step_by_step_pauses_after_each_stage_until_the_owner_continues(tmp_path: Path) -> None:
    runner = pipeline(tmp_path)
    runner.start("Owner", date(2026, 10, 19), "guided")
    seen = []
    for _ in range(3):
        for _ in range(200):
            status = runner.current()
            if status and status.state == "paused" and status.paused_after not in seen:
                break
            time.sleep(0.02)
        assert status is not None and status.state == "paused"
        seen.append(status.paused_after)
        runner.resume()
    assert seen == ["sort", "plan", "shots"]
    assert runner.thread is not None
    runner.thread.join(10)
    status = runner.current()
    assert status is not None and status.state == "failed"
    with AssetLibrary(tmp_path / "ws", root=tmp_path) as library:
        shots = [library.get(i) for i in status.new_shots]
    # Step by step leaves new shots for the owner to approve.
    assert shots and all(not s.approved and not s.rejected for s in shots)
