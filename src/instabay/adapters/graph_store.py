"""FR-09, FR-10: transactional authorization around each remote operation and journal update."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Session, select

from instabay.adapters.graph_http import require_live
from instabay.adapters.graph_models import GraphConfig, GraphJob, LiveConfigurationError
from instabay.core.schemas import Approval, Post, Publication
from instabay.core.tables import BrandVersionRow, GraphJobRow, PublicationRow, RunRow, SlotRow
from instabay.repository import Repository


class GraphStore:
    """FR-09: SQLite write locks prevent rejection/edit races during individual HTTP calls."""

    def __init__(self, repository: Repository, *, confirm_live: bool) -> None:
        self.repository, self.confirm_live = repository, confirm_live

    @contextmanager
    def locked(self, post_id: str) -> Iterator[tuple[Session, Post, Approval]]:
        with Session(self.repository.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            post, approval = self.repository._authorized_post(session, post_id)
            require_live(self.confirm_live)
            slot = session.get(SlotRow, post.slot_id)
            run = session.get(RunRow, slot.run_id) if slot else None
            brand = session.get(BrandVersionRow, post.brand_hash)
            if run is None or run.demo or brand is None or not brand.frozen:
                raise LiveConfigurationError(
                    "Live publishing requires a non-demo run and HUMAN-frozen brand"
                )
            yield session, post, approval
            session.commit()

    @staticmethod
    def job(session: Session, job_id: str) -> GraphJob:
        row = session.get(GraphJobRow, job_id)
        if row is None:
            raise KeyError("Unknown Graph operation")
        return GraphJob.model_validate_json(row.job_json)

    @staticmethod
    def save(session: Session, job: GraphJob) -> None:
        job = GraphJob.model_validate({**job.model_dump(), "updated_at": datetime.now(UTC)})
        session.merge(GraphJobRow(id=job.id, post_id=job.post_id, job_json=job.model_dump_json()))

    @staticmethod
    def receipt(
        session: Session, post: Post, config: GraphConfig, account_id: str
    ) -> Publication | None:
        row = session.exec(select(PublicationRow).where(PublicationRow.post_id == post.id)).first()
        if row is None:
            return None
        if (
            row.mode != "live"
            or row.account_id != account_id
            or row.api_version != config.api_version
            or row.graph_login != config.login
        ):
            raise LiveConfigurationError(
                "Existing publication belongs to a different mode/account/version"
            )
        if row.content_hash != post.content_hash:
            raise ValueError("Publication content mismatch")
        return Publication.model_validate(row.model_dump())

    def finish(self, job_id: str, config: GraphConfig, account_id: str) -> Publication:
        with Session(self.repository.engine) as read:
            post_id = self.job(read, job_id).post_id
        with self.locked(post_id) as (session, post, _approval):
            existing = self.receipt(session, post, config, account_id)
            if existing:
                return existing
            job = self.job(session, job_id)
            if job.phase != "published" or not job.media_id or not job.container_id:
                raise ValueError("A real published media ID is required for a live receipt")
            receipt = Publication(
                id=str(uuid4()),
                post_id=post.id,
                approval_id=job.approval_id,
                idempotency_key=post.idempotency_key,
                content_hash=post.content_hash,
                mode="live",
                outbox_path="",
                published_at=datetime.now(UTC),
                media_id=job.media_id,
                container_id=job.container_id,
                account_id=job.account_id,
                api_version=job.api_version,
                payload_hash=job.payload_hash,
                graph_login=job.login,
            )
            session.add(PublicationRow(**receipt.model_dump(mode="json")))
            return receipt
