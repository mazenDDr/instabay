"""FR-09, FR-10: dry-run publishing cannot bypass the stored approval transaction."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal, Protocol

from instabay.adapters.storage import OutboxWriter, PublicationStore, UnapprovedPublishError
from instabay.core.schemas import Approval, Boundary, Post, Publication

__all__ = ["DryRunPublisher", "FileOutboxWriter", "Publisher", "UnapprovedPublishError"]


class Publisher(Protocol):
    """FR-10: an adapter exports/publishes only content authorized by stored decisions."""

    def publish(self, post_id: str) -> Publication:
        """FR-09: raise UnapprovedPublishError before publishing unapproved content."""
        ...


class DryRunEnvelope(Boundary):
    """FR-10: an intent artifact, explicitly distinct from a live API payload."""

    mode: Literal["dry_run"] = "dry_run"
    post: Post
    approval: Approval
    caption_en: str
    caption_ar: str
    media_ready_for_live: bool = False
    reference_only: bool = True
    reference_attribution: str
    note: str = "Dry-run intent only. No request was made to Instagram."


class FileOutboxWriter:
    """FR-10: atomically export JSON after authorization, without any network call."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(self, post: Post, approval: Approval) -> str:
        """FR-10: use content-derived filenames; failed writes leave no receipt."""
        envelope = DryRunEnvelope(
            post=post,
            approval=approval,
            caption_en=post.full_caption("en"),
            caption_ar=post.full_caption("ar"),
            reference_attribution=(
                "See assets/photos/README.md and manifest.json "
                "for source-resort credit and licenses."
            ),
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / f"{post.idempotency_key}.json"
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, prefix=".pending-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(envelope.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return str(destination)


class DryRunPublisher:
    """FR-09: the store holds its write lock across approval check, I/O and receipt."""

    def __init__(
        self,
        store: PublicationStore,
        outbox: Path = Path("outbox"),
        *,
        writer: OutboxWriter | None = None,
    ) -> None:
        self.store = store
        self.writer = writer if writer is not None else FileOutboxWriter(outbox)

    def publish(self, post_id: str) -> Publication:
        """FR-09, FR-10: no live mode exists in this adapter; stored approval is mandatory."""
        return self.store.publish_approved(post_id, self.writer)
