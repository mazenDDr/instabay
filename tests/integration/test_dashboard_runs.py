"""FR-09, FR-11: the dashboard lists real run databases and stores the owner's decisions."""

from pathlib import Path

import pytest_socket
from fastapi.testclient import TestClient

from instabay.dashboard.app import create_app
from instabay.repository import Repository
from tests.integration.test_week import request, week
from tests.support import demo_brand


def test_dashboard_lists_runs_and_stores_hash_bound_decisions(tmp_path: Path) -> None:
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    runs = tmp_path / "outputs"
    (runs / "demo").mkdir(parents=True)
    with week(runs / "demo") as runner:
        result = runner.start(request())
    client = TestClient(
        create_app(workspace=tmp_path / "ws", brand=demo_brand(), runs=runs, root=tmp_path)
    )
    listed = client.get("/api/runs").json()
    assert [r["run_id"] for r in listed] == ["2026-w42"]
    posts = listed[0]["posts"]
    assert len(posts) == len(result.post_ids) and all(p["decision"] is None for p in posts)
    db = listed[0]["db"]
    flagged = next((p for p in posts if p["flags"]), None)
    target = flagged or posts[0]
    body = {"db": db, "post_id": target["id"], "decision": "APPROVED", "actor": "Owner"}
    # Flagged or not, approving needs no reason (owner decision 2026-10-13).
    assert client.post("/api/decision", json=body).json() == {"decision": "APPROVED"}
    assert client.post("/api/decision", json={**body, "db": "../x.sqlite"}).status_code == 404
    reject = {"db": db, "post_id": posts[-1]["id"], "decision": "REJECTED", "actor": "Owner"}
    assert client.post("/api/decision", json=reject).status_code == 422
    repository = Repository(runs / "demo" / "db.sqlite")
    stored = repository.latest_approval(target["id"])
    assert stored is not None and stored.actor == "Owner"
    assert stored.content_hash == repository.post(target["id"]).content_hash
    repository.close()
    after = client.get("/api/runs").json()[0]["posts"]
    assert next(p for p in after if p["id"] == target["id"])["decision"] == "APPROVED"
