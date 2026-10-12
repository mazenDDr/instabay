"""FR-09, FR-10: synthetic offline contracts; never real Instagram credentials or posts."""

from pathlib import Path

import pytest
from sqlmodel import Session, select

from instabay.adapters.graph_models import (
    GraphAPIError,
    GraphContainerError,
    GraphJob,
    GraphPendingError,
    GraphProtocolError,
    GraphRateLimitError,
    GraphReconciliationRequired,
    GraphTransportError,
)
from instabay.core.schemas import Post, PostFormat
from instabay.core.tables import GraphJobRow, PublicationRow
from instabay.repository import Repository
from tests.graph_support import live_post, publisher


def journal(repository: Repository) -> GraphJob:
    with Session(repository.engine) as session:
        return GraphJob.model_validate_json(session.exec(select(GraphJobRow)).one().job_json)


def receipts(repository: Repository) -> int:
    with Session(repository.engine) as session:
        return len(session.exec(select(PublicationRow)).all())


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INSTABAY_MODE", "live")
    repo = Repository(tmp_path / "state.sqlite")
    yield repo
    repo.close()


@pytest.mark.parametrize("format", ["photo", "carousel", "reel"])
def test_finished_and_idempotent_receipt_after_restart(
    repository: Repository, format: PostFormat
) -> None:
    post = live_post(repository, format)
    engine, transport = publisher(repository, "finished" if format == "photo" else format)
    receipt = engine.publish(post.id)
    assert receipt.mode == "live" and receipt.media_id == "3000" and receipt.container_id == "2000"
    assert receipt.account_id == "1000" and receipt.content_hash == post.content_hash
    assert journal(repository).phase == "published" and receipts(repository) == 1
    # A new adapter instance with the same journal returns the receipt without a request.
    engine2, unused = publisher(repository, "finished")
    assert engine2.publish(post.id) == receipt
    assert unused.calls == []
    transport.assert_consumed()
    with pytest.raises(ValueError, match="cannot be edited"):
        repository.save_post(Post.model_validate({**post.model_dump(), "revision": 1}))


@pytest.mark.parametrize("scenario", ["error", "expired"])
def test_terminal_container_never_publishes_or_recreates(
    repository: Repository, scenario: str
) -> None:
    post = live_post(repository)
    engine, transport = publisher(repository, scenario)
    with pytest.raises(GraphContainerError):
        engine.publish(post.id)
    assert journal(repository).phase == scenario and receipts(repository) == 0
    with pytest.raises(GraphContainerError):
        engine.publish(post.id)
    assert all(path != "/1000/media_publish" for _, path, _ in transport.calls)
    transport.assert_consumed()


def test_pending_bounded_to_five_minutes_then_resumes_existing_container(
    repository: Repository,
) -> None:
    post = live_post(repository)
    sleeps: list[float] = []
    engine, transport = publisher(repository, "pending", sleeps=sleeps)
    with pytest.raises(GraphPendingError):
        engine.publish(post.id)
    assert sleeps == [60] * 5 and journal(repository).container_id == "2000"
    assert receipts(repository) == 0
    assert engine.publish(post.id).media_id == "3000"
    assert (
        sum(method == "POST" and path == "/1000/media" for method, path, _ in transport.calls) == 1
    )
    transport.assert_consumed()


@pytest.mark.parametrize("scenario", ["rate_create", "rate_publish"])
def test_known_rate_rejection_retries_explicitly_with_idempotent_journal(
    repository: Repository, scenario: str
) -> None:
    post = live_post(repository)
    engine, transport = publisher(repository, scenario)
    with pytest.raises(GraphRateLimitError):
        engine.publish(post.id)
    assert receipts(repository) == 0
    assert journal(repository).phase == ("prepared" if scenario == "rate_create" else "ready")
    assert engine.publish(post.id).media_id == "3000"
    transport.assert_consumed()


@pytest.mark.parametrize("scenario", ["timeout_publish", "server_error_publish"])
def test_ambiguous_publish_never_retries_or_uses_container_as_media_id(
    repository: Repository, scenario: str
) -> None:
    post = live_post(repository)
    engine, transport = publisher(repository, scenario)
    with pytest.raises(GraphTransportError):
        engine.publish(post.id)
    assert journal(repository).phase == "publishing" and journal(repository).media_id is None
    with pytest.raises(GraphReconciliationRequired):
        engine.publish(post.id)
    assert receipts(repository) == 0
    assert sum(path == "/1000/media_publish" for _, path, _ in transport.calls) == 1
    transport.assert_consumed()


@pytest.mark.parametrize(
    "scenario,error",
    [("timeout_create", GraphTransportError), ("malformed_id", GraphProtocolError)],
)
def test_unknown_creation_outcome_never_duplicates_container(
    repository: Repository, scenario: str, error: type[Exception]
) -> None:
    post = live_post(repository)
    engine, transport = publisher(repository, scenario)
    with pytest.raises(error):
        engine.publish(post.id)
    assert journal(repository).phase == "creating"
    with pytest.raises(GraphReconciliationRequired):
        engine.publish(post.id)
    assert receipts(repository) == 0
    transport.assert_consumed()


@pytest.mark.parametrize(
    "scenario,error",
    [
        ("quota", GraphAPIError),
        ("remote_quota", GraphAPIError),
        ("unknown_status", GraphProtocolError),
        ("published_status", GraphReconciliationRequired),
    ],
)
def test_fail_closed_on_quota_unknown_status_or_unassociated_published_container(
    repository: Repository, scenario: str, error: type[Exception]
) -> None:
    post = live_post(repository)
    engine, transport = publisher(repository, scenario)
    with pytest.raises(error):
        engine.publish(post.id)
    assert receipts(repository) == 0
    assert all(path != "/1000/media_publish" for _, path, _ in transport.calls)
    transport.assert_consumed()


def test_crash_after_accepted_creation_keeps_prior_committed_intent(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    post = live_post(repository)
    engine, transport = publisher(repository, "finished")
    save = engine.store.save

    def crash(session: Session, job: GraphJob) -> None:
        if job.phase == "processing":
            raise RuntimeError("Synthetic crash before committing container response")
        save(session, job)

    monkeypatch.setattr(engine.store, "save", crash)
    with pytest.raises(RuntimeError):
        engine.publish(post.id)
    assert journal(repository).phase == "creating"
    assert len(transport.calls) == 2
    engine2, fresh = publisher(repository, "finished")
    with pytest.raises(GraphReconciliationRequired):
        engine2.publish(post.id)
    assert fresh.calls == []


def test_public_bytes_changed_during_processing_block_publish(repository: Repository) -> None:
    import httpx

    from instabay.adapters.graph_http import HttpxMediaVerifier
    from instabay.adapters.graph_models import MediaValidationError
    from tests.graph_support import GRAPH_CONFIG

    post = live_post(repository)
    engine, transport = publisher(repository, "media_changed")
    reads = []

    def changed_bytes(request: httpx.Request) -> httpx.Response:
        reads.append(request.url)
        return httpx.Response(
            200,
            content=b"jpeg" if len(reads) == 1 else b"evil",
            headers={"content-type": "image/jpeg"},
        )

    verifier = HttpxMediaVerifier(GRAPH_CONFIG, transport=httpx.MockTransport(changed_bytes))
    engine.verifier = verifier
    try:
        with pytest.raises(MediaValidationError):
            engine.publish(post.id)
        assert len(reads) == 2 and receipts(repository) == 0
        assert journal(repository).phase == "ready"
        transport.assert_consumed()
    finally:
        verifier.close()
