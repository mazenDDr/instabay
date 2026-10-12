"""FR-06, NFR-03: recorded worker contracts, no external requests or GPU work."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from instabay.video.backends.stub import StubVideoBackend
from instabay.video.files import RenderError
from instabay.video.keyframes import stub_recipe
from instabay.video.remote import WorkerClient
from tests.unit.test_video_recipe import ROOT, shotlist


@pytest.mark.parametrize("outcome", ["complete", "failed", "timeout", "wrong_hash", "corrupt"])
def test_worker_poll_download_provenance(tmp_path: Path, outcome: str) -> None:
    recipe = stub_recipe(shotlist(), ROOT)
    video = b"synthetic-video-contract"
    contact = b"synthetic-contact-contract"
    result = {
        "recipe_hash": recipe.recipe_hash,
        "backend": "stub",
        "file": "/remote/reel.mp4",
        "file_sha256": hashlib.sha256(video).hexdigest(),
        "contact_sheet": "/remote/contact-sheet.jpg",
        "contact_sha256": hashlib.sha256(contact).hexdigest(),
        "frame_hashes": ["0" * 64],
        "seconds": 1,
        "cost_usd": 0,
        "ai_disclosure": False,
        "reference_only": True,
        "qa": {
            "spec_ok": True,
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "duration_s": 15,
            "size_bytes": len(video),
            "moov_at_front": True,
            "violations": ["pending semantic QA"],
            "status": "needs_review",
        },
    }

    def transport(request):
        assert request.headers["x-instabay-worker-key"] == "synthetic-worker-fixture-only-key"
        if request.url.path == "/jobs":
            assert json.loads(request.content) == recipe.model_dump(mode="json")
            return httpx.Response(
                202,
                json={
                    "id": "0" * 64 if outcome == "wrong_hash" else recipe.recipe_hash,
                    "status": "queued",
                    "artifact_urls": [],
                },
            )
        if request.url.path.endswith("result.json"):
            return httpx.Response(200, json=result)
        if request.url.path.endswith("recipe.json"):
            return httpx.Response(200, json=recipe.model_dump(mode="json"))
        if request.url.path.endswith("reel.mp4"):
            return httpx.Response(200, content=b"corrupt" if outcome == "corrupt" else video)
        if request.url.path.endswith("contact-sheet.jpg"):
            return httpx.Response(200, content=contact)
        return httpx.Response(
            200,
            json={
                "id": recipe.recipe_hash,
                "status": "failed"
                if outcome == "failed"
                else "queued"
                if outcome == "timeout"
                else "complete",
                "artifact_urls": [],
            },
        )

    client = WorkerClient(
        "http://gpu-box:8000",
        "synthetic-worker-fixture-only-key",
        ROOT,
        tmp_path,
        StubVideoBackend(),
        confirm_worker=True,
        transport=httpx.MockTransport(transport),
        polls=1,
        poll_seconds=0,
    )
    if outcome == "complete":
        actual = client.render(recipe)
        assert Path(actual.file).read_bytes() == video and actual.qa.status == "needs_review"
    else:
        with pytest.raises(RenderError):
            client.render(recipe)
    client.close()


def test_worker_explicit_opt_in_before_network(tmp_path: Path) -> None:
    client = WorkerClient(
        "http://gpu-box:8000",
        "synthetic-worker-fixture-only-key",
        ROOT,
        tmp_path,
        StubVideoBackend(),
        transport=httpx.MockTransport(lambda _: pytest.fail("network")),
    )
    with pytest.raises(RenderError, match="HUMAN"):
        client.render(stub_recipe(shotlist(), ROOT))
    client.close()
