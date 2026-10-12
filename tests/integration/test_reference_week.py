"""FR-05, FR-09: real mixed media and source evidence persist before the approval interrupt."""

from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from instabay.adapters.publisher import DryRunPublisher
from instabay.adapters.storage import UnapprovedPublishError
from instabay.approval import show_post
from instabay.core.schemas import BrandInput, WorkflowInput
from instabay.graph import ApprovalPendingError, WeekRunner
from instabay.repository import Repository
from tests.unit.test_content_evidence import ROOT, campaign


def test_mixed_week_preserves_artifacts_sources_and_unapproved_boundary(tmp_path):
    brand, evidence, _, _ = campaign()
    db = tmp_path / "week.sqlite"
    out = tmp_path / "outbox"
    kwargs = dict(content_evidence=evidence, content_root=ROOT, reference_brand=brand)
    with WeekRunner(
        db,
        tmp_path / "checkpoint.sqlite",
        out,
        BrandInput(brief="Reference study", owner_answers={}),
        **kwargs,
    ) as runner:
        result = runner.start(
            WorkflowInput(run_id="reference-w42", week_start=date(2026, 10, 12), demo=True)
        )
        assert result.status == "approval_pending" and not out.exists()
        posts = [runner.repository.post(i) for i in result.post_ids]
        assert [p.format for p in posts] == [
            "photo",
            "carousel",
            "reel",
            "photo",
            "carousel",
            "reel",
            "photo",
        ]
        for post in posts:
            assert post.evidence and post.evidence.reference_only
            review = runner.repository.review(post.id)
            assert review.check_path == "human_pending" and review.judge is None and review.flagged
            if post.format != "reel":
                assert post.photo_artifact
                assert len(post.photo_artifact.files) == (1 if post.format == "photo" else 3)
                assert all(Path(p.file).exists() for p in post.photo_artifact.files)
            with pytest.raises(UnapprovedPublishError):
                DryRunPublisher(runner.repository, out).publish(post.id)
        with pytest.raises(ApprovalPendingError):
            runner.resume("reference-w42")
        text = StringIO()
        show_post(runner.repository, posts[1].id, Console(file=text, width=160))
        assert (
            "Human review pending" in text.getvalue()
            and "System1 checks passed" not in text.getvalue()
        )
        assert "Reethi Faru" in text.getvalue() and "Photo 3" in text.getvalue()
        saved = [p.content_hash for p in posts]
    repository = Repository(db)
    assert [repository.post(i).content_hash for i in result.post_ids] == saved
    repository.close()


def test_reference_command_refuses_live_mode_before_creating_outputs(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from instabay.cli import app

    monkeypatch.setenv("INSTABAY_MODE", "live")
    output = tmp_path / "preview"
    result = CliRunner().invoke(app, ["reference-week", "--output", str(output)])
    assert result.exit_code != 0 and "dry_run" in result.output
    assert not output.exists()
