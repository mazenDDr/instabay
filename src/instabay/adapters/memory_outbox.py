"""NFR-07: in-memory outbox fake, defined before filesystem publishing."""

from instabay.core.schemas import Approval, Post


class MemoryOutbox:
    """FR-10: record only the snapshots the authorization store permits."""

    def __init__(self) -> None:
        self.written: dict[str, Post] = {}

    def write(self, post: Post, approval: Approval) -> str:
        """FR-10: replay the same approved post without a second artifact."""
        self.written[post.idempotency_key] = post
        return f"memory://{post.idempotency_key}"
