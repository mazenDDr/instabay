"""FR-09: safety regression committed before the GraphPublisher implementation."""

from pathlib import Path

import pytest

from instabay.adapters.graph_models import GraphConfig
from instabay.adapters.graph_transport import GraphResponse
from instabay.adapters.storage import UnapprovedPublishError
from instabay.repository import Repository
from tests.support import draft_post


class ForbiddenTransport:
    def request(self, *args: object, **kwargs: object) -> GraphResponse:
        raise AssertionError("Unapproved content must not reach any Graph request")


def test_graph_publish_requires_stored_approval_before_any_io(tmp_path: Path) -> None:
    from instabay.adapters.graph_publisher import GraphPublisher

    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = draft_post(repository)
        publisher = GraphPublisher(
            repository, GraphConfig(), ForbiddenTransport(), confirm_live=False
        )
        with pytest.raises(UnapprovedPublishError):
            publisher.publish(post.id)
    finally:
        repository.close()
