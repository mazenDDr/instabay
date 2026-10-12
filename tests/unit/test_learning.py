"""FR-09, FR-11, FR-13: receipt guard, atomic updates, fidelity skips and isolation."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlmodel import Session, select

import instabay.repository as repository_module
from instabay.adapters.insights import SimulatedInsights
from instabay.adapters.memory_outbox import MemoryOutbox
from instabay.adapters.storage import UnapprovedPublishError
from instabay.core.learning import FidelityResult
from instabay.core.schemas import ApprovalRequest
from instabay.core.tables import MetricRow
from instabay.repository import Repository
from sim.world import AudienceWorld
from tests.support import draft_post

SCOPE = "a" * 64


def inputs(repository: Repository, status: str = "confirmed"):
    post = draft_post(repository)
    slot = repository.slots("2026-w42")[0]
    arm = slot.arm
    executed = (
        arm.model_copy(update={"hook_style": "statement"})
        if status == "leaked"
        else arm
        if status == "confirmed"
        else None
    )
    fidelity = FidelityResult(
        post_id=post.id,
        content_hash=post.content_hash,
        planned_arm=arm,
        executed_arm=executed,
        status=status,
        source="synthetic-unit-label",
        reason="Test only",
    )
    repository.approve(
        post.id, ApprovalRequest(decision="APPROVED", actor="synthetic-unit-test", seconds_spent=0)
    )
    publication = repository.publish_approved(post.id, MemoryOutbox())
    metrics = SimulatedInsights(AudienceWorld(7)).fetch(post, slot, publication, fidelity)
    return post, metrics, fidelity


@pytest.mark.parametrize("status", ["confirmed", "leaked", "unverified"])
def test_fidelity_controls_all_four_updates(tmp_path: Path, status: str) -> None:
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post, metrics, fidelity = inputs(repository, status)
        receipt = repository.record_metrics(SCOPE, metrics, fidelity)
        assert receipt.learned == (status == "confirmed")
        beliefs = repository.posteriors(SCOPE)
        assert len(beliefs) == (4 if status == "confirmed" else 0)
        for belief in beliefs:
            assert belief.alpha == pytest.approx(1 + 20 * metrics.engagement_rate)
            assert belief.beta == pytest.approx(1 + 20 * (1 - metrics.engagement_rate))
        assert repository.learning_record(post.id) == receipt
        with Session(repository.engine) as session:
            assert len(session.exec(select(MetricRow)).all()) == 7
        assert repository.posteriors("b" * 64) == []
    finally:
        repository.close()


def test_retry_and_concurrent_retry_do_not_double_learn(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "state.sqlite")
    try:
        _, metrics, fidelity = inputs(repository)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(repository.record_metrics, SCOPE, metrics, fidelity) for _ in range(2)
            ]
            receipts = [future.result() for future in futures]
        assert receipts[0] == receipts[1]
        beliefs = repository.posteriors(SCOPE)
        assert len(beliefs) == 4
        assert all(row.alpha + row.beta == pytest.approx(22) for row in beliefs)
        assert repository.record_metrics(SCOPE, metrics, fidelity) == receipts[0]
        assert repository.posteriors(SCOPE) == beliefs
        changed = metrics.model_copy(update={"likes": metrics.likes + 1})
        with pytest.raises(ValueError, match="cannot be replaced"):
            repository.record_metrics(SCOPE, changed, fidelity)
        assert repository.posteriors(SCOPE) == beliefs
    finally:
        repository.close()


def test_failure_rolls_back_metrics_receipt_and_partial_updates(
    tmp_path: Path, monkeypatch
) -> None:
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post, metrics, fidelity = inputs(repository)
        original = repository_module.update_posterior
        calls = 0

        def fail_second(belief, rate):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic storage failure")
            return original(belief, rate)

        monkeypatch.setattr(repository_module, "update_posterior", fail_second)
        with pytest.raises(RuntimeError, match="synthetic storage failure"):
            repository.record_metrics(SCOPE, metrics, fidelity)
        assert repository.learning_record(post.id) is None
        assert repository.posteriors(SCOPE) == []
        with Session(repository.engine) as session:
            assert session.exec(select(MetricRow)).all() == []
        monkeypatch.setattr(repository_module, "update_posterior", original)
        assert repository.record_metrics(SCOPE, metrics, fidelity).learned
    finally:
        repository.close()


def test_unpublished_and_wrong_content_cannot_learn(tmp_path: Path) -> None:
    source = Repository(tmp_path / "source.sqlite")
    target = Repository(tmp_path / "target.sqlite")
    try:
        _, metrics, fidelity = inputs(source)
        draft_post(target)
        with pytest.raises(UnapprovedPublishError, match="authorized stored publication"):
            target.record_metrics(SCOPE, metrics, fidelity)
        with pytest.raises(ValueError, match="exact stored post"):
            source.record_metrics(
                SCOPE, metrics.model_copy(update={"content_hash": "b" * 64}), fidelity
            )
        mismatched = fidelity.model_copy(
            update={
                "planned_arm": fidelity.planned_arm.model_copy(update={"hook_style": "statement"})
            }
        )
        with pytest.raises(ValueError):
            source.record_metrics(SCOPE, metrics, mismatched)
        assert target.posteriors(SCOPE) == source.posteriors(SCOPE) == []
    finally:
        source.close()
        target.close()


def test_phase2_posterior_schema_migrates_without_losing_legacy_rows(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE posterior (factor TEXT, level TEXT, alpha FLOAT, beta FLOAT, "
            "PRIMARY KEY(factor, level))"
        )
        connection.execute("INSERT INTO posterior VALUES ('format', 'photo', 4.2, 56.8)")
    repository = Repository(path)
    assert repository.posteriors(SCOPE) == []
    assert repository.posteriors("legacy")[0].alpha == 4.2
    repository.close()
    reopened = Repository(path)
    assert reopened.posteriors("legacy")[0].beta == 56.8
    reopened.close()
