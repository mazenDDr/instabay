"""FR-09, FR-10, NFR-07: paused graph and stored approvals survive CLI/process restarts."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from langgraph.types import Command
from typer.testing import CliRunner

from instabay.adapters.fake_llm import FakeLLMMissingFixture
from instabay.cli import app
from instabay.core.schemas import ApprovalRequest, BrandInput, Post, WorkflowInput
from instabay.graph import ApprovalPendingError, WeekRunner
from instabay.repository import Repository


def inputs() -> BrandInput:
    return BrandInput.model_validate(
        yaml.safe_load(Path("config/brand_inputs.example.yaml").read_text())
    )


def week(tmp_path: Path, fixtures: Path = Path("tests/fixtures/llm")) -> WeekRunner:
    return WeekRunner(
        tmp_path / "db.sqlite",
        tmp_path / "checkpoints.sqlite",
        tmp_path / "outbox",
        inputs(),
        fixtures,
    )


def request() -> WorkflowInput:
    return WorkflowInput(run_id="2026-w42", week_start=date(2026, 10, 12))


def test_week_interrupts_then_new_process_resumes_only_stored_decisions(tmp_path: Path) -> None:
    with week(tmp_path) as runner:
        stopped = runner.start(request())
        assert stopped.status == "approval_pending"
        assert len(stopped.post_ids) == 7
        assert runner.fake.calls == 43
        assert len([row for row in runner.calls.calls() if row.template_name == "judge"]) == 21
        assert not (tmp_path / "outbox").exists()
        snapshot = runner.graph.get_state(runner._config(request().run_id))
        assert snapshot.next == ("human_approval",)
        assert any(task.interrupts for task in snapshot.tasks)
    with week(tmp_path) as runner:
        assert runner.start(request()) == stopped
        assert runner.fake.calls == 0
        assert runner.service.usage.calls == 43
        with pytest.raises(ApprovalPendingError):
            runner.resume(request().run_id)
        for post_id in stopped.post_ids:
            runner.repository.approve(
                post_id,
                ApprovalRequest(
                    decision="APPROVED",
                    actor="test-human",
                    reason="Synthetic integration-test approval; concept only",
                    seconds_spent=1,
                ),
            )
    with week(tmp_path) as runner:
        result = runner.resume(request().run_id)
        assert result.status == "completed"
        assert runner.fake.calls == 0
        receipts = runner.repository.publications(request().run_id)
        assert len(receipts) == 7
        assert runner.resume(request().run_id) == result
        assert len(runner.repository.publications(request().run_id)) == 7
    files = list((tmp_path / "outbox").glob("*.json"))
    assert len(files) == 7
    for path in files:
        payload = json.loads(path.read_text())
        assert payload["mode"] == "dry_run"
        assert payload["approval"]["decision"] == "APPROVED"
        assert (
            payload["approval"]["content_hash"] == Post.model_validate(payload["post"]).content_hash
        )
        assert payload["media_ready_for_live"] is False


def test_graph_resume_payload_cannot_forge_human_approvals(tmp_path: Path) -> None:
    with week(tmp_path) as runner:
        runner.start(request())
        with pytest.raises(ApprovalPendingError):
            runner.graph.invoke(
                Command(resume={"decision": "APPROVED", "actor": "not-stored"}),
                runner._config(request().run_id),
            )
        assert runner.repository.publications(request().run_id) == []
        assert not (tmp_path / "outbox").exists()


def test_three_cli_commands_support_edit_reject_and_resume(tmp_path: Path) -> None:
    cli = CliRunner()
    options = [
        "--db",
        str(tmp_path / "db.sqlite"),
        "--checkpoints",
        str(tmp_path / "checkpoint.sqlite"),
        "--outbox",
        str(tmp_path / "outbox"),
    ]
    started = cli.invoke(app, ["demo", *options])
    assert started.exit_code == 0, started.output
    assert "STOPPED at human approval" in started.output
    responses = (
        "approve\n\n"
        + "edit\nSofter CTA\nA quieter morning. Save this for later.\n\n"
        + "reject\nSkip today\n"
        + "approve\n\n" * 3
        + "approve\nConcept only; dry run\n"
    )
    decided = cli.invoke(
        app,
        ["approve", "--db", str(tmp_path / "db.sqlite"), "--actor", "test-human"],
        input=responses,
    )
    assert decided.exit_code == 0, decided.output
    assert "Stored 7 human decisions" in decided.output
    assert not (tmp_path / "outbox").exists()
    finished = cli.invoke(app, ["resume", *options])
    assert finished.exit_code == 0, finished.output
    assert "6 dry-run exports" in finished.output
    repository = Repository(tmp_path / "db.sqlite")
    edited = repository.latest_approval("2026-w42-tue-1")
    assert edited and edited.decision == "EDITED" and edited.diff and edited.seconds_spent > 0
    assert repository.latest_approval("2026-w42-wed-1").decision == "REJECTED"
    assert len(list((tmp_path / "outbox").glob("*.json"))) == 6
    replay = cli.invoke(app, ["demo", *options])
    assert replay.exit_code == 0, replay.output
    assert "Already completed: 6" in replay.output
    repository.close()


def test_failed_draft_continues_from_checkpoint_without_overwriting_saved_posts(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    shutil.copytree("tests/fixtures/llm", fixtures)
    missing = fixtures / "copy_en__2026-w42-wed-1.json"
    original = missing.read_bytes()
    missing.unlink()
    with week(tmp_path, fixtures) as runner:
        with pytest.raises(FakeLLMMissingFixture):
            runner.start(request())
        assert runner.result(request().run_id).status == "in_progress"
        with pytest.raises(ApprovalPendingError, match="Generation is incomplete"):
            runner.resume(request().run_id)
        saved = runner.repository.post("2026-w42-mon-1").content_hash
    missing.write_bytes(original)
    with week(tmp_path, fixtures) as runner:
        result = runner.start(request())
        assert result.status == "approval_pending"
        assert len(result.post_ids) == 7
        assert runner.repository.post("2026-w42-mon-1").content_hash == saved
        assert runner.repository.publications(request().run_id) == []


def test_live_environment_never_selects_a_live_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    result = CliRunner().invoke(app, ["demo", "--db", str(tmp_path / "db.sqlite")])
    assert result.exit_code == 2
    assert "offline dry_run" in result.output
    assert not (tmp_path / "db.sqlite").exists()


def test_trace_environment_cannot_turn_offline_demo_into_network_traffic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with week(tmp_path) as runner:
        assert runner.start(request()).status == "approval_pending"
