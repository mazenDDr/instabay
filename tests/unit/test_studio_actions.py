"""FR-04, FR-09: undoable library actions, Trash, revoked decisions and run controls."""

import base64
import time
from datetime import date
from pathlib import Path

import pytest
import pytest_socket
from fastapi.testclient import TestClient

from instabay.adapters.storage import UnapprovedPublishError
from instabay.assets.library import AssetLibrary
from instabay.core.schemas import ApprovalRequest
from instabay.dashboard.app import create_app
from tests.integration.test_week import request, week
from tests.support import demo_brand
from tests.unit.test_assets import jpeg, owner_photo
from tests.unit.test_generate_job import pipeline


@pytest.fixture
def library(tmp_path: Path):
    with AssetLibrary(tmp_path / "ws", root=tmp_path) as lib:
        yield lib


def test_bulk_actions_undo_trash_and_purge(library: AssetLibrary) -> None:
    a, b = owner_photo(library, 1, "spa"), owner_photo(library, 2, "local")
    seq = library.act("Owner", "pillar", "2 set", [a.id, b.id], owner_pillar="guests")
    assert {x.pillar for x in library.all()} == {"guests"}
    assert library.undo(seq) == "2 set"
    assert (library.get(a.id).pillar, library.get(b.id).pillar) == ("spa", "local")
    library.act("Owner", "delete", "1 trashed", [a.id], deleted_at="2026-10-13T00:00:00")
    assert [x.id for x in library.all()] == [b.id]
    assert [x.id for x in library.all(trash=True)] == [a.id] and not library.get(a.id).usable
    library.undo()
    assert len(library.all()) == 2
    library.act("Owner", "delete", "both", [a.id, b.id], deleted_at="2026-10-13T00:00:00")
    assert library.purge([a.id, b.id], in_use={b.id}) == 1
    with pytest.raises(KeyError):
        library.get(a.id)
    assert library.get(b.id).deleted_at  # kept: a generated post still uses it
    again = library.add(
        library.path(library.get(b.id)).read_bytes(), added_by="Owner", rights_confirmed=True
    )
    assert again.id == b.id and again.deleted_at is None  # re-upload restores from Trash
    with pytest.raises(ValueError, match="Nothing to undo"):
        AssetLibrary(library.workspace, root=library.root).undo(99999)
    kinds = [r["kind"] for r in library.activity()]
    assert kinds[:2] == ["delete", "delete"]


def test_revoked_decision_makes_a_post_pending_and_blocks_publish(tmp_path: Path) -> None:
    with week(tmp_path) as runner:
        result = runner.start(request())
        repo = runner.repository
        post_id = result.post_ids[0]
        reason = "checked" if repo.review(post_id).flagged else ""
        repo.approve(
            post_id,
            ApprovalRequest(decision="APPROVED", actor="Owner", reason=reason, seconds_spent=1),
        )
        revoked = repo.approve(
            post_id, ApprovalRequest(decision="REVOKED", actor="Owner", seconds_spent=1)
        )
        assert revoked.decision == "REVOKED"
        latest = repo.latest_approval(post_id)
        assert latest is not None and latest.decision == "REVOKED"
        with pytest.raises(UnapprovedPublishError):
            runner.publisher.publish(post_id)


def test_studio_api_trash_undo_activity_and_bulk_decisions(tmp_path: Path) -> None:
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    runs = tmp_path / "outputs"
    (runs / "demo").mkdir(parents=True)
    with week(runs / "demo") as runner:
        result = runner.start(request())
    client = TestClient(
        create_app(workspace=tmp_path / "ws", brand=demo_brand(), runs=runs, root=tmp_path)
    )
    data = "data:image/jpeg;base64," + base64.b64encode(jpeg((5, 6, 7))).decode()
    up = {"name": "a.jpg", "data_base64": data, "rights_confirmed": True, "added_by": "Owner"}
    asset = client.post("/api/assets", json=up).json()
    moved = client.post("/api/assets/action", json={"ids": [asset["id"]], "action": "delete"})
    assert moved.json()["summary"] == "1 photo moved to Trash"
    assert client.get("/api/assets").json() == [] and len(client.get("/api/trash").json()) == 1
    assert client.post("/api/undo", json={}).json()["undone"] == "1 photo moved to Trash"
    assert len(client.get("/api/assets").json()) == 1
    bad = {"ids": [asset["id"]], "action": "pillar", "pillar": "nope"}
    assert client.post("/api/assets/action", json=bad).status_code == 422
    assert (
        client.get(f"/media/assets/{asset['id']}?download=1")
        .headers["content-disposition"]
        .startswith("attachment")
    )
    db = client.get("/api/runs").json()[0]["db"]
    ids = result.post_ids[:2]
    body = {"db": db, "post_ids": ids, "decision": "APPROVED", "actor": "Owner", "reason": "ok"}
    assert client.post("/api/decision/bulk", json=body).json()["done"] == ids
    revoke = {**body, "decision": "REVOKED", "post_ids": ids[:1]}
    assert client.post("/api/decision/bulk", json=revoke).json()["done"] == ids[:1]
    posts = {p["id"]: p for p in client.get("/api/runs").json()[0]["posts"]}
    assert posts[ids[0]]["decision"] is None and posts[ids[1]]["decision"] == "APPROVED"
    kinds = {r["kind"] for r in client.get("/api/activity").json()}
    assert {"upload", "delete", "decision"} <= kinds
    moved_run = client.post("/api/runs/delete", json={"db": db}).json()["moved_to"]
    assert moved_run.startswith("data/backup-runs/") and client.get("/api/runs").json() == []


def test_pipeline_can_be_stopped_and_run_again_as_a_new_version(tmp_path: Path) -> None:
    runner = pipeline(tmp_path)
    runner.start("Owner", date(2026, 10, 19), "guided")
    for _ in range(200):
        if (status := runner.current()) and status.state == "paused":
            break
        time.sleep(0.02)
    runner.cancel()
    assert runner.thread is not None
    runner.thread.join(10)
    status = runner.current()
    assert status is not None and status.state == "cancelled"
    (tmp_path / "outputs" / "studio" / "week-2026-10-19").mkdir(parents=True, exist_ok=True)
    again = runner.start("Owner", date(2026, 10, 19), "guided", again=True)
    assert again.run_id == "week-2026-10-19-v2"
    runner.cancel()
    runner.thread.join(10)
