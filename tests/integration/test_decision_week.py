"""FR-08, FR-09: cascade is wired into real graph checkpoints; approval never bypassed."""

from datetime import date
from pathlib import Path

import pytest
from sqlmodel import Session, select

from instabay.core.schemas import ApprovalRequest, WorkflowInput
from instabay.core.tables import DecisionScoreRow
from instabay.graph import ApprovalPendingError, WeekRunner
from tests.decision_support import engine_for, profile_for
from tests.integration.test_week import inputs


def test_calibrated_fake_week_skips_judge_but_interrupts_for_human_and_survives_restart(
    tmp_path: Path,
) -> None:
    request = WorkflowInput(run_id="2026-w42", week_start=date(2026, 10, 12))
    with WeekRunner(
        tmp_path / "author.sqlite",
        tmp_path / "author-check.sqlite",
        tmp_path / "author-out",
        inputs(),
    ) as author:
        author.start(request)
        brand = author.repository.brand(
            author.repository.post(request.run_id + "-mon-1").brand_hash
        )
        posts = [
            (author.repository.post(slot.id), slot)
            for slot in author.repository.slots(request.run_id)
        ]
        engine = engine_for(tmp_path / "decisions", posts, brand)
        profile = profile_for(brand)
    with WeekRunner(
        tmp_path / "state.sqlite",
        tmp_path / "checks.sqlite",
        tmp_path / "outbox",
        inputs(),
        decision_engine=engine,
        calibration=profile,
        allow_synthetic_decisions=True,
    ) as runner:
        stopped = runner.start(request)
        assert stopped.status == "approval_pending"
        assert not (tmp_path / "outbox").exists()
        with pytest.raises(ApprovalPendingError):
            runner.resume(request.run_id)
        with Session(runner.repository.engine) as session:
            assert len(session.exec(select(DecisionScoreRow)).all()) == 70
        for post_id in stopped.post_ids:
            review = runner.repository.review(post_id)
            # Fixed audit may call the judge; other posts have no invented judge samples.
            if not review.decision_trace["judge_called"]:
                assert review.judge is None
            runner.repository.approve(
                post_id,
                ApprovalRequest(
                    decision="APPROVED",
                    actor="synthetic-test-human",
                    reason="Offline fixture integration only",
                    seconds_spent=1,
                ),
            )
        count = runner.fake.calls
        assert count < 43
    with WeekRunner(
        tmp_path / "state.sqlite",
        tmp_path / "checks.sqlite",
        tmp_path / "outbox",
        inputs(),
        decision_engine=engine,
        calibration=profile,
        allow_synthetic_decisions=True,
    ) as resumed:
        assert resumed.resume(request.run_id).status == "completed"
        assert len(resumed.repository.publications(request.run_id)) == 7
        assert resumed.fake.calls == 0
