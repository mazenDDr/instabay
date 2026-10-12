"""FR-07, FR-09, NFR-04: approval, mode, brand and media guards execute before HTTP."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from instabay.adapters.graph_http import StubMediaVerifier
from instabay.adapters.graph_models import (
    GraphPendingError,
    GraphReconciliationRequired,
    LiveConfigurationError,
    MediaValidationError,
)
from instabay.adapters.graph_publisher import GraphPublisher
from instabay.adapters.graph_transport import GraphResponse
from instabay.adapters.publisher import DryRunPublisher
from instabay.adapters.storage import UnapprovedPublishError
from instabay.cli import app
from instabay.core.schemas import ApprovalRequest, Post, canonical_hash
from instabay.core.tables import BrandVersionRow, GraphJobRow, RunRow
from instabay.repository import Repository
from tests.graph_support import GRAPH_CONFIG, live_post, publisher
from tests.support import draft_post, save_review


class Forbidden:
    def request(self, *args: object, **kwargs: object) -> GraphResponse:
        raise AssertionError("No Graph I/O expected")

    def verify(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("No media I/O expected")


@pytest.mark.parametrize(
    "guard",
    [
        "missing",
        "rejected",
        "stale",
        "dry_run",
        "unconfirmed",
        "demo",
        "unfrozen",
        "reference",
        "concept",
        "missing_manifest",
        "generated_no_disclosure",
    ],
)
def test_all_guards_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guard: str
) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = live_post(repository, approved=guard not in {"missing", "stale"})
        if guard == "stale":
            repository.approve(
                post.id,
                ApprovalRequest(
                    decision="APPROVED",
                    actor="synthetic-test-human",
                    reason="fixture",
                    seconds_spent=1,
                ),
            )
            repository.save_post(Post.model_validate({**post.model_dump(), "revision": 1}))
        if guard == "rejected":
            repository.approve(
                post.id,
                ApprovalRequest(
                    decision="REJECTED",
                    actor="synthetic-test-human",
                    reason="fixture rejection",
                    seconds_spent=1,
                ),
            )
        if guard in {"unfrozen", "demo"}:
            with Session(repository.engine) as session:
                if guard == "unfrozen":
                    row = session.get(BrandVersionRow, post.brand_hash)
                    row.frozen = False
                else:
                    row = session.get(RunRow, "graph-fixture-w42")
                    row.demo = True
                session.add(row)
                session.commit()
        if guard in {"reference", "concept", "missing_manifest", "generated_no_disclosure"}:
            updates: dict[str, object] = {}
            if guard == "reference":
                manifest = post.media_manifest.model_dump()
                manifest["reference_only"] = True
                updates["media_manifest"] = manifest
            elif guard == "concept":
                updates["media_status"] = "concept_only"
            elif guard == "missing_manifest":
                updates["media_manifest"] = None
            else:
                manifest = post.media_manifest.model_dump()
                manifest["generated"] = True
                updates["media_manifest"] = manifest
            post = Post.model_validate({**post.model_dump(), **updates})
            repository.save_post(post)
            save_review(repository, post)
            repository.approve(
                post.id,
                ApprovalRequest(
                    decision="APPROVED",
                    actor="synthetic-test-human",
                    reason="fixture",
                    seconds_spent=1,
                ),
            )
        if guard == "dry_run":
            monkeypatch.setenv("INSTABAY_MODE", "dry_run")
        engine = GraphPublisher(
            repository,
            GRAPH_CONFIG,
            Forbidden(),
            account_id="1000",
            confirm_live=guard != "unconfirmed",
            verifier=Forbidden(),
        )
        with pytest.raises((UnapprovedPublishError, LiveConfigurationError, MediaValidationError)):
            engine.publish(post.id)
    finally:
        repository.close()


def test_rejection_during_polling_prevents_next_io_and_active_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = live_post(repository)
        engine, transport = publisher(repository, "pending")

        def reject(seconds: float) -> None:
            repository.approve(
                post.id,
                ApprovalRequest(
                    decision="REJECTED",
                    actor="synthetic-test-human",
                    reason="stop fixture",
                    seconds_spent=1,
                ),
            )

        engine.sleep = reject
        with pytest.raises(UnapprovedPublishError):
            engine.publish(post.id)
        assert len(transport.calls) == 3
        with pytest.raises(ValueError, match="active Graph"):
            repository.save_post(Post.model_validate({**post.model_dump(), "revision": 1}))
    finally:
        repository.close()


def test_manifest_edit_invalidates_old_approval_before_media_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = live_post(repository)
        data = post.model_dump()
        data["media_manifest"]["assets"][0]["url"] = "https://cdn.example.org/different.jpg"
        changed = Post.model_validate(data)
        assert changed.content_hash != post.content_hash
        repository.save_post(changed)
        engine = GraphPublisher(
            repository,
            GRAPH_CONFIG,
            Forbidden(),
            account_id="1000",
            confirm_live=True,
            verifier=Forbidden(),
        )
        with pytest.raises(UnapprovedPublishError):
            engine.publish(post.id)
    finally:
        repository.close()


def test_preflight_only_job_can_be_corrected_and_stale_job_cannot_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = live_post(repository)
        engine, transport = publisher(repository, "quota")
        from instabay.adapters.graph_models import GraphAPIError, GraphJob

        with pytest.raises(GraphAPIError):
            engine.publish(post.id)
        with Session(repository.engine) as session:
            old = GraphJob.model_validate_json(session.exec(select(GraphJobRow)).one().job_json)
        changed = Post.model_validate({**post.model_dump(), "revision": 1})
        repository.save_post(changed)
        save_review(repository, changed)
        repository.approve(
            post.id,
            ApprovalRequest(
                decision="APPROVED",
                actor="synthetic-test-human",
                reason="corrected fixture",
                seconds_spent=1,
            ),
        )
        with pytest.raises(UnapprovedPublishError):
            engine._step(old, lambda p, a, j: j)
        assert len(transport.calls) == 1
    finally:
        repository.close()


def test_legacy_migration_preserves_hash_approval_and_dry_receipt(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    repository = Repository(path)
    post = draft_post(repository)
    assert post.content_hash == canonical_hash(post.model_dump(exclude={"media_manifest"}))
    repository.approve(
        post.id,
        ApprovalRequest(
            decision="APPROVED", actor="synthetic-test-human", reason="fixture", seconds_spent=1
        ),
    )
    receipt = DryRunPublisher(repository, tmp_path / "outbox").publish(post.id)
    repository.close()
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE post DROP COLUMN media_json")
        for name in (
            "media_id",
            "container_id",
            "account_id",
            "api_version",
            "payload_hash",
            "graph_login",
        ):
            connection.execute(f"ALTER TABLE publication DROP COLUMN {name}")
    migrated = Repository(path)
    try:
        assert migrated.post(post.id).content_hash == post.content_hash
        assert DryRunPublisher(migrated, tmp_path / "outbox").publish(post.id) == receipt
    finally:
        migrated.close()


def test_native_cli_rejects_unapproved_before_credentials_or_http(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    repository = Repository(path)
    post = draft_post(repository)
    repository.close()
    result = CliRunner().invoke(app, ["graph-publish", "--db", str(path), "--post-id", post.id])
    assert result.exit_code == 2 and "UnapprovedPublishError" in result.output


@pytest.mark.parametrize("format", ["photo", "carousel"])
def test_concurrent_publishers_never_duplicate_posts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format: str
) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = live_post(repository, format)

        class CountingTransport:
            def __init__(self) -> None:
                self.creates: list[dict[str, str]] = []
                self.publishes: list[dict[str, str]] = []

            def request(self, method: str, path: str, params: dict[str, str]) -> GraphResponse:
                if path.endswith("content_publishing_limit"):
                    body = {"data": [{"quota_usage": 0}]}
                elif method == "POST" and path.endswith("/media"):
                    self.creates.append(params)
                    body = {"id": str(2000 + len(self.creates))}
                elif method == "POST":
                    self.publishes.append(params)
                    body = {"id": "3000"}
                else:
                    body = {"status_code": "FINISHED"}
                return GraphResponse(status_code=200, body=body)

        transport = CountingTransport()
        barrier = Barrier(2)

        def run():
            barrier.wait()
            engine = GraphPublisher(
                repository,
                GRAPH_CONFIG,
                transport,
                account_id="1000",
                confirm_live=True,
                verifier=StubMediaVerifier(),
                sleep=lambda _: None,
            )
            try:
                return engine.publish(post.id)
            except (GraphPendingError, GraphReconciliationRequired):
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: run(), range(2)))
        final = GraphPublisher(
            repository,
            GRAPH_CONFIG,
            transport,
            account_id="1000",
            confirm_live=True,
            verifier=StubMediaVerifier(),
            sleep=lambda _: None,
        ).publish(post.id)
        assert final.media_id == "3000" and len(transport.publishes) == 1
        assert len(transport.creates) == (3 if format == "carousel" else 1)
    finally:
        repository.close()


def test_native_cli_exposes_numeric_rate_hint_without_provider_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from instabay.adapters.graph_http import HttpxGraphTransport

    monkeypatch.setenv("INSTABAY_MODE", "live")
    path = tmp_path / "state.sqlite"
    repository = Repository(path)
    post = live_post(repository)
    engine, transport = publisher(repository, "finished")
    engine.publish(post.id)
    transport.assert_consumed()
    repository.close()
    monkeypatch.setenv("INSTAGRAM_USER_ID", "1000")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "synthetic-header-sentinel")
    monkeypatch.setattr(
        HttpxGraphTransport,
        "request",
        lambda *args: GraphResponse(
            status_code=429,
            body={"error": {"code": 4, "message": "synthetic-header-sentinel"}},
            retry_after_s=45,
        ),
    )
    result = CliRunner().invoke(
        app, ["graph-insights", "--db", str(path), "--post-id", post.id, "--confirm-live"]
    )
    assert result.exit_code == 2
    assert "GraphRateLimitError; code=4" in result.output
    assert "at least 45 seconds" in result.output
    assert "sentinel" not in result.output
