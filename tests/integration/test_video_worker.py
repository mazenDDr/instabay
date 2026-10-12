"""FR-06, NFR-04: private worker auth, durable idempotency and actual end-to-end render."""

import socket
from pathlib import Path

import pytest
import pytest_socket
from fastapi.testclient import TestClient

from gpu_worker.server import create_app
from instabay.video.keyframes import stub_recipe
from instabay.video.studio import VideoStudio
from instabay.video.worker import RenderQueue
from tests.unit.test_video_recipe import ROOT, shotlist

SYNTHETIC_TOKEN = "synthetic-worker-fixture-only-key"


def test_worker_auth_queue_restart_and_verified_download(tmp_path: Path) -> None:
    # ASGI's event loop needs a local socketpair. Internet/TCP sockets remain forbidden.
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    studio = VideoStudio(tmp_path / "worker.sqlite", ROOT, tmp_path / "renders")
    recipe = stub_recipe(shotlist(), ROOT, preset="ultrafast")
    with TestClient(create_app(studio, SYNTHETIC_TOKEN)) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.post("/jobs", json=recipe.model_dump(mode="json")).status_code == 401
        assert client.get("/jobs/" + "0" * 64).status_code == 401
        headers = {"x-instabay-worker-key": SYNTHETIC_TOKEN}
        first = client.post("/jobs", headers=headers, json=recipe.model_dump(mode="json"))
        assert first.status_code == 202 and first.json()["id"] == recipe.recipe_hash
        assert first.json()["status"] == "queued"
        assert (
            client.post("/jobs", headers=headers, json=recipe.model_dump(mode="json")).json()
            == first.json()
        )
        assert (
            client.get(
                f"/jobs/{recipe.recipe_hash}/artifacts/reel.mp4", headers=headers
            ).status_code
            == 409
        )
        queue = RenderQueue(studio)
        assert queue.run_once() and not queue.run_once()
        assert queue.status(recipe.recipe_hash).status == "complete"
        assert (
            client.get(f"/jobs/{recipe.recipe_hash}", headers=headers).json()["status"]
            == "complete"
        )
        artifact = client.get(f"/jobs/{recipe.recipe_hash}/artifacts/reel.mp4", headers=headers)
        assert artifact.status_code == 200 and len(artifact.content) > 1000
        assert (
            client.get(
                f"/jobs/{recipe.recipe_hash}/artifacts/private.env", headers=headers
            ).status_code
            == 404
        )
    with TestClient(create_app(studio, SYNTHETIC_TOKEN)) as restarted:
        assert (
            restarted.get(f"/jobs/{recipe.recipe_hash}", headers=headers).json()["status"]
            == "complete"
        )
