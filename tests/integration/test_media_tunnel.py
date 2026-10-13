"""FR-07, FR-09: attaching tunnel media binds exact bytes and forces a fresh approval."""

from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from instabay.adapters.media_tunnel import manifest, photo_files, ready, tunnel_url
from instabay.core.schemas import ApprovalRequest, BrandInput, Post, WorkflowInput
from instabay.graph import WeekRunner
from instabay.graph_commands import _recheck
from instabay.repository import Repository
from tests.unit.test_content_evidence import ROOT, campaign

BASE = "https://quiet-reef-sample.trycloudflare.com"


def photo_post(tmp_path: Path) -> Post:
    return _week(tmp_path)[0]


def _week(tmp_path: Path) -> tuple[Post, Path]:
    brand, evidence, _, _ = campaign()
    with WeekRunner(
        tmp_path / "week.sqlite",
        tmp_path / "checkpoint.sqlite",
        tmp_path / "outbox",
        BrandInput(brief="Reference study", owner_answers={}),
        content_evidence=evidence,
        content_root=ROOT,
        reference_brand=brand,
    ) as runner:
        result = runner.start(
            WorkflowInput(run_id="reference-w42", week_start=date(2026, 10, 12), demo=True)
        )
        return runner.repository.post(result.post_ids[0]), tmp_path / "week.sqlite"


def test_tunnel_address_is_read_from_cloudflared_output() -> None:
    line = "INF |  https://quiet-reef-sample.trycloudflare.com                   |"
    assert tunnel_url(line) == BASE
    assert tunnel_url("INF Requesting new quick Tunnel on trycloudflare.com...") is None


def test_manifest_binds_bytes_and_a_new_revision_needs_new_approval(tmp_path: Path) -> None:
    post = photo_post(tmp_path)
    assert post.format == "photo" and post.photo_artifact is not None
    with pytest.raises(ValueError, match="Reference-only"):
        photo_files(post, Path.cwd())
    files = [Path(f.file) for f in post.photo_artifact.files]
    media = manifest(post, files, BASE, "Owner")
    asset = media.assets[0]
    assert asset.url == f"{BASE}/{post.photo_artifact.files[0].file_sha256}.jpg"
    assert (asset.width, asset.height, asset.size_bytes) == (1080, 1350, files[0].stat().st_size)
    assert not media.reference_only
    updated = ready(post, media)
    assert updated.revision == post.revision + 1 and updated.media_status == "ready"
    assert updated.content_hash != post.content_hash


def test_instagram_aspect_ratio_is_checked(tmp_path: Path) -> None:
    post = photo_post(tmp_path)
    tall = tmp_path / "tall.jpg"
    Image.new("RGB", (1080, 1920)).save(tall, "JPEG")
    with pytest.raises(ValueError, match=r"4:5 to 1\.91:1"):
        manifest(post, [tall], BASE, "Owner")


def test_attached_revision_is_rechecked_so_it_can_be_approved(tmp_path: Path) -> None:
    post, db = _week(tmp_path)
    assert post.photo_artifact is not None
    files = [Path(f.file) for f in post.photo_artifact.files]
    repository = Repository(db)
    try:
        updated = ready(post, manifest(post, files, BASE, "Owner"))
        repository.save_post(updated)
        request = ApprovalRequest(decision="APPROVED", actor="Owner", seconds_spent=1)
        with pytest.raises(ValueError, match="current checks"):
            repository.approve(post.id, request)
        review = _recheck(repository, updated)
        assert review.content_hash == updated.content_hash and review.rules.passed
        assert repository.approve(post.id, request).content_hash == updated.content_hash
    finally:
        repository.close()
