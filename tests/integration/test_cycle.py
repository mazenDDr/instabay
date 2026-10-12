"""FR-09 to FR-13: real offline graph cycles, synthetic decisions only in temporary state."""

from pathlib import Path

import pytest
import yaml
from sqlmodel import Session, select
from typer.testing import CliRunner

from instabay.adapters.fake_llm import FakeLLMMissingFixture
from instabay.adapters.insights import SimulatedInsights
from instabay.cli import app
from instabay.core.schemas import ApprovalRequest, BrandInput
from instabay.core.tables import LearningRow, MetricRow, PosteriorRow
from instabay.cycle import CycleInput, CycleRunner
from instabay.repository import Repository


def runner(root: Path) -> CycleRunner:
    return CycleRunner(
        root / "db.sqlite",
        root / "checkpoints.sqlite",
        root / "outbox",
        BrandInput.model_validate(
            yaml.safe_load(Path("config/brand_inputs.example.yaml").read_text())
        ),
    )


def decide(root: Path, run_id: str, week: int) -> None:
    repository = Repository(root / "db.sqlite")
    try:
        for index, post_id in enumerate(repository.post_ids(run_id)):
            decision = "REJECTED" if week == 3 or (week == 1 and index == 0) else "APPROVED"
            edit = week == 1 and index == 1
            repository.approve(
                post_id,
                ApprovalRequest(
                    decision="EDITED" if edit else decision,
                    actor="synthetic-cycle-test",
                    seconds_spent=1,
                    reason="Synthetic acceptance decision; never a real approval",
                    en_caption="Leave room for a slower moment. Save this idea." if edit else None,
                ),
            )
    finally:
        repository.close()


def test_cycle_restarts_pauses_each_week_and_replays_same_seed(tmp_path: Path) -> None:
    outcomes = []
    for root in (tmp_path / "first", tmp_path / "second"):
        request = CycleInput()
        assert runner(root).run(request).status == "approval_pending"
        repository = Repository(root / "db.sqlite")
        assert len(repository.post_ids("cycle-w01")) == 7
        with pytest.raises(KeyError, match="Unknown run"):
            repository.run("cycle-w02")
        assert repository.publications("cycle-w01") == []
        assert repository.posteriors("a" * 64) == []
        repository.close()
        assert not (root / "outbox").exists()
        for week in range(1, 4):
            paused = runner(root).run(request)
            assert paused.current_run_id == f"cycle-w{week:02d}"
            assert len(paused.reports) == week - 1
            decide(root, paused.current_run_id, week)
            result = runner(root).run(request)
            assert len(result.reports) == week
        assert result.status == "completed"
        assert [row.exported for row in result.reports] == [6, 7, 0]
        assert [row.learned for row in result.reports] == [5, 7, 0]
        assert [row.unverified for row in result.reports] == [1, 0, 0]
        assert result.reports[-1].engagement_rate is None
        repository = Repository(root / "db.sqlite")
        with Session(repository.engine) as session:
            beliefs_before = [row.model_dump() for row in session.exec(select(PosteriorRow)).all()]
            metrics_before = [row.model_dump() for row in session.exec(select(MetricRow)).all()]
            assert len(session.exec(select(LearningRow)).all()) == 13
        plans = [repository.slots(f"cycle-w{week:02d}") for week in range(1, 4)]
        assert [slot.arm for slot in plans[0]] != [slot.arm for slot in plans[1]]
        repository.close()
        assert runner(root).run(request) == result
        repository = Repository(root / "db.sqlite")
        with Session(repository.engine) as session:
            assert [
                row.model_dump() for row in session.exec(select(PosteriorRow)).all()
            ] == beliefs_before
            assert [
                row.model_dump() for row in session.exec(select(MetricRow)).all()
            ] == metrics_before
        repository.close()
        assert len(list((root / "outbox").glob("*.json"))) == 13
        outcomes.append((result, plans, beliefs_before, metrics_before))
    assert outcomes[0] == outcomes[1]


def test_cycle_config_and_missing_keys_fail_before_generation(tmp_path: Path) -> None:
    worker = runner(tmp_path)
    with pytest.raises(FakeLLMMissingFixture):
        worker.run(CycleInput(weeks=13))
    assert not worker.db.exists()
    worker.run(CycleInput())
    for changed in (CycleInput(seed=8), CycleInput(weeks=2)):
        with pytest.raises(ValueError, match="different inputs"):
            worker.run(changed)
    repository = Repository(worker.db)
    assert repository.publications("cycle-w01") == []
    repository.close()


def test_partial_analysis_recovers_without_duplicate_updates(tmp_path: Path, monkeypatch) -> None:
    worker = runner(tmp_path)
    worker.run(CycleInput())
    decide(tmp_path, "cycle-w01", 1)
    original = SimulatedInsights.fetch
    calls = 0

    def fail_third(self, *args):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("synthetic insights interruption")
        return original(self, *args)

    monkeypatch.setattr(SimulatedInsights, "fetch", fail_third)
    with pytest.raises(RuntimeError, match="synthetic insights interruption"):
        worker.run(CycleInput())
    repository = Repository(worker.db)
    assert len(repository.publications("cycle-w01")) == 6
    with Session(repository.engine) as session:
        assert len(session.exec(select(LearningRow)).all()) == 2
    repository.close()
    monkeypatch.setattr(SimulatedInsights, "fetch", original)
    result = runner(tmp_path).run(CycleInput())
    assert result.current_run_id == "cycle-w02"
    assert result.reports[0].learned == 5
    repository = Repository(worker.db)
    with Session(repository.engine) as session:
        assert len(session.exec(select(LearningRow)).all()) == 6
        assert sum(
            row.alpha + row.beta - 2 for row in session.exec(select(PosteriorRow)).all()
        ) == pytest.approx(5 * 4 * 20)
    repository.close()


def test_cli_pauses_and_live_flags_are_rejected(tmp_path: Path) -> None:
    args = [
        "cycle",
        "--weeks",
        "3",
        "--db",
        str(tmp_path / "db.sqlite"),
        "--checkpoints",
        str(tmp_path / "checkpoints.sqlite"),
        "--outbox",
        str(tmp_path / "outbox"),
    ]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.exception
    assert "approval_pending" in result.output
    assert "--run-id cycle-w01" in result.output
    assert not (tmp_path / "outbox").exists()
    for flags in (["--live"], ["--confirm-live"], ["--live", "--confirm-live"]):
        result = CliRunner().invoke(app, [*args, *flags])
        assert result.exit_code == 2
        assert "deferred" in result.output
