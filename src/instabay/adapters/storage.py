"""FR-09, FR-10: authorization/persistence boundary, independent of publishing I/O."""

from typing import Protocol

from instabay.core.schemas import Approval, Post, Publication


class UnapprovedPublishError(PermissionError):
    """FR-09: no matching stored APPROVED/EDITED decision exists."""


class OutboxWriter(Protocol):
    """FR-10: a fake is written first; file exports have the same interface."""

    def write(self, post: Post, approval: Approval) -> str:
        """FR-10: return the artifact location after writing the approved snapshot."""
        ...


class PublicationStore(Protocol):
    """FR-09: check authorization and write the receipt under one storage lock."""

    def publish_approved(self, post_id: str, writer: OutboxWriter) -> Publication:
        """FR-09: raise before writer I/O if approval is absent, rejected or stale."""
        ...
