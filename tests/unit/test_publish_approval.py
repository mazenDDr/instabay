"""FR-09: approval regression tests written before the publisher implementation."""

from pathlib import Path

import pytest

from instabay.adapters.memory_outbox import MemoryOutbox
from instabay.adapters.publisher import DryRunPublisher, UnapprovedPublishError
from instabay.core.schemas import ApprovalRequest, Copy, Post
from instabay.repository import Repository
from tests.support import draft_post, save_review


def test_publish_without_stored_approval_raises_before_any_io(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    outbox = MemoryOutbox()
    with pytest.raises(UnapprovedPublishError):
        DryRunPublisher(repository, writer=outbox).publish(post.id)
    assert outbox.written == {}
    assert repository.publications("2026-w42") == []


def test_rejection_cannot_publish(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    repository.approve(
        post.id,
        ApprovalRequest(
            decision="REJECTED", actor="test-human", reason="Not suitable", seconds_spent=1
        ),
    )
    outbox = MemoryOutbox()
    with pytest.raises(UnapprovedPublishError):
        DryRunPublisher(repository, writer=outbox).publish(post.id)
    assert outbox.written == {}


def test_content_changed_after_approval_requires_new_approval(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    repository.approve(
        post.id, ApprovalRequest(decision="APPROVED", actor="test-human", seconds_spent=2)
    )
    changed = Post.model_validate(
        {
            **post.model_dump(),
            "revision": 1,
            "en": Copy(caption="Changed caption", alt_text=post.en.alt_text),
        }
    )
    repository.save_post(changed)
    save_review(repository, changed)
    outbox = MemoryOutbox()
    with pytest.raises(UnapprovedPublishError):
        DryRunPublisher(repository, writer=outbox).publish(post.id)
    assert outbox.written == {}
