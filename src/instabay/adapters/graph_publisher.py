"""FR-07, FR-09, FR-10: approved media, bounded polling and durable Graph publishing."""

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlmodel import Session, select

from instabay.adapters.graph_http import MediaVerifier, graph_request, validate_media
from instabay.adapters.graph_models import (
    GraphAPIError,
    GraphConfig,
    GraphContainerError,
    GraphID,
    GraphJob,
    GraphPendingError,
    GraphProtocolError,
    GraphReconciliationRequired,
    LiveConfigurationError,
    MediaValidationError,
)
from instabay.adapters.graph_store import GraphStore
from instabay.adapters.graph_transport import GraphTransport
from instabay.adapters.storage import UnapprovedPublishError
from instabay.core.schemas import Approval, Post, Publication, canonical_hash
from instabay.core.tables import GraphJobRow
from instabay.repository import Repository


class GraphPublisher:
    """FR-10: no automatic POST retry after timeouts, malformed IDs, crashes or 5xx."""

    def __init__(
        self,
        repository: Repository,
        config: GraphConfig,
        transport: GraphTransport,
        *,
        confirm_live: bool,
        account_id: str = "",
        verifier: MediaVerifier | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = GraphStore(repository, confirm_live=confirm_live)
        self.config, self.transport, self.account_id = config, transport, account_id
        self.verifier, self.sleep = verifier, sleep

    @staticmethod
    def caption(post: Post) -> str:
        """FR-05: one approved EN+AR caption, one hashtag list, both AI disclosure lines."""
        en, ar = post.en.caption, post.ar.caption
        if post.ai_disclosure:
            en += "\nScenes created with AI."
            ar += "\nمشاهد أُنشئت بالذكاء الاصطناعي."
        result = en + "\n\n" + ar + "\n" + " ".join(post.hashtags)
        if (
            len(result) > 2200
            or len(re.findall(r"#[\w]+", result)) > 30
            or len(re.findall(r"@[\w]+", result)) > 20
        ):
            raise MediaValidationError(
                "Combined live caption exceeds character/hashtag/mention limits"
            )
        return result

    def _payload(self, post: Post, job: GraphJob | None = None) -> dict[str, str]:
        manifest = post.media_manifest
        if manifest is None or manifest.format != post.format:
            raise MediaValidationError(
                "Attach an approved media manifest matching the planned format"
            )
        if post.media_status != ("rendered" if post.format == "reel" else "ready"):
            raise MediaValidationError(
                "Reference photos and concept-only reels cannot be published"
            )
        if manifest.generated and not post.ai_disclosure:
            raise MediaValidationError("Generated media requires EN and AR AI disclosure")
        validate_media(manifest, self.config)
        payload = {"caption": self.caption(post)}
        if post.format == "photo":
            payload.update(
                image_url=manifest.assets[0].url,
                alt_text=post.en.alt_text + " / " + post.ar.alt_text,
            )
        elif post.format == "reel":
            payload.update(
                media_type="REELS", video_url=manifest.assets[0].url, share_to_feed="true"
            )
            if manifest.cover:
                payload["cover_url"] = manifest.cover.url
        else:
            payload.update(media_type="CAROUSEL", children=",".join(job.child_ids) if job else "")
        return payload

    @staticmethod
    def _id(body: dict[str, object]) -> str:
        value = body.get("id")
        if not isinstance(value, str) or not value.isdigit():
            raise GraphProtocolError("Graph response lacks a numeric resource ID")
        return value

    def _quota(self) -> None:
        body = graph_request(
            self.transport,
            "GET",
            f"/{self.account_id}/content_publishing_limit",
            {"fields": "quota_usage,config"},
        )
        data = body.get("data")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise GraphProtocolError("Publishing limit response is missing")
        usage, config = data[0].get("quota_usage"), data[0].get("config")
        cap = self.config.publish_cap
        if isinstance(config, dict):
            remote_cap = config.get("quota_total")
            if isinstance(remote_cap, int) and remote_cap > 0:
                cap = min(cap, remote_cap)
        if not isinstance(usage, int) or isinstance(usage, bool) or usage < 0:
            raise GraphProtocolError("Publishing quota is invalid")
        if usage >= cap:
            raise GraphAPIError(36003)

    def _step(
        self, job: GraphJob, action: Callable[[Post, Approval, GraphJob], GraphJob]
    ) -> GraphJob:
        with self.store.locked(job.post_id) as (session, post, approval):
            current = self.store.job(session, job.id)
            if current.content_hash != post.content_hash:
                raise UnapprovedPublishError(
                    "Graph operation no longer matches the approved snapshot"
                )
            result = action(post, approval, current)
            self.store.save(session, result)
            return result

    def _intent(self, job: GraphJob, phase: str) -> GraphJob:
        def action(post: Post, approval: Approval, current: GraphJob) -> GraphJob:
            required = "prepared" if phase == "creating" else "ready"
            if (
                current.phase != required
                or job.phase != required
                or current.child_ids != job.child_ids
                or current.container_id != job.container_id
            ):
                raise GraphPendingError(
                    "Another publisher advanced this operation; retry from the journal"
                )
            return GraphJob.model_validate(
                {**current.model_dump(), "phase": phase, "approval_id": approval.id}
            )

        return self._step(job, action)

    def _create(self, job: GraphJob, *, child: bool) -> GraphJob:
        job = self._intent(
            job, "creating"
        )  # Commit intent before POST; crash must remain ambiguous.
        rejection: GraphAPIError | None = None

        def action(post: Post, approval: Approval, current: GraphJob) -> GraphJob:
            nonlocal rejection
            if current.phase != "creating":
                raise GraphPendingError("Operation advanced concurrently")
            manifest = post.media_manifest
            assert manifest is not None
            if child:
                payload = {
                    "image_url": manifest.assets[len(current.child_ids)].url,
                    "is_carousel_item": "true",
                }
            else:
                payload = self._payload(post, current)
            try:
                resource_id = self._id(
                    graph_request(self.transport, "POST", f"/{self.account_id}/media", payload)
                )
            except GraphAPIError as error:
                rejection = error
                return current.model_copy(update={"phase": "prepared"})
            if child:
                return current.model_copy(
                    update={"phase": "prepared", "child_ids": [*current.child_ids, resource_id]}
                )
            return current.model_copy(update={"phase": "processing", "container_id": resource_id})

        job = self._step(job, action)
        if rejection:
            raise rejection
        return job

    def _status(self, job: GraphJob) -> GraphJob:
        def action(post: Post, approval: Approval, current: GraphJob) -> GraphJob:
            body = graph_request(
                self.transport, "GET", f"/{current.container_id}", {"fields": "status_code"}
            )
            status = body.get("status_code")
            if not isinstance(status, str) or status not in {
                "IN_PROGRESS",
                "FINISHED",
                "ERROR",
                "EXPIRED",
                "PUBLISHED",
            }:
                raise GraphProtocolError("Unsupported container status")
            phase: str = current.phase
            if phase == "processing":
                phase = {"FINISHED": "ready", "ERROR": "error", "EXPIRED": "expired"}.get(
                    str(status), phase
                )
            return current.model_copy(update={"phase": phase, "last_status": status})

        return self._step(job, action)

    def publish(self, post_id: str) -> Publication:
        """FR-09: authorize before verifier, quota, poll or mutation; receipts are idempotent."""
        with self.store.locked(post_id) as (session, post, approval):
            TypeAdapter(GraphID).validate_python(self.account_id)
            existing = self.store.receipt(session, post, self.config, self.account_id)
            if existing:
                return existing
            payload = self._payload(post)
            payload_hash = canonical_hash(
                {
                    "parent": payload,
                    "manifest": post.media_manifest.model_dump(mode="json")
                    if post.media_manifest
                    else None,
                    "login": self.config.login,
                }
            )
            job_id = canonical_hash(
                {
                    "key": post.idempotency_key,
                    "account": self.account_id,
                    "version": self.config.api_version,
                    "payload": payload_hash,
                }
            )
            row = session.get(GraphJobRow, job_id)
            job = (
                GraphJob.model_validate_json(row.job_json)
                if row
                else GraphJob(
                    id=job_id,
                    post_id=post_id,
                    content_hash=post.content_hash,
                    approval_id=approval.id,
                    account_id=self.account_id,
                    api_version=self.config.api_version,
                    login=self.config.login,
                    payload_hash=payload_hash,
                    updated_at=datetime.now(UTC),
                )
            )
            others = session.exec(select(GraphJobRow).where(GraphJobRow.post_id == post_id)).all()
            if any(
                r.id != job_id
                and (
                    (other := GraphJob.model_validate_json(r.job_json)).phase
                    not in {"error", "expired", "prepared"}
                    or (bool(other.child_ids) and other.phase == "prepared")
                )
                for r in others
            ):
                raise LiveConfigurationError(
                    "Post already has an active Graph operation under another profile"
                )
            if row is None:
                self.store.save(session, job)
        if job.phase == "published":
            return self.store.finish(job.id, self.config, self.account_id)
        if job.phase == "creating":
            raise GraphReconciliationRequired(
                "HUMAN: unknown container creation outcome; do not create another container"
            )
        if job.phase == "publishing":
            job = self._status(job)
            raise GraphReconciliationRequired(
                "HUMAN: uncertain publish response; container ID is not a published media ID"
            )
        if job.phase in {"error", "expired"}:
            raise GraphContainerError("Container is terminal: " + job.phase)
        if job.phase == "prepared":

            def verify(post: Post, approval: Approval, current: GraphJob) -> GraphJob:
                if current.phase != "prepared":
                    raise GraphPendingError("Operation advanced concurrently")
                if self.verifier is None:
                    raise LiveConfigurationError("A media verifier is mandatory")
                assert post.media_manifest is not None
                self.verifier.verify(post.media_manifest, self.config)
                self._quota()
                return current.model_copy(update={"verified_media": True})

            job = self._step(job, verify)
            with Session(self.store.repository.engine) as session:
                post = self.store.repository._post(session, job.post_id)
            assert post.media_manifest is not None
            if post.format == "carousel":
                while len(job.child_ids) < len(post.media_manifest.assets):
                    job = self._create(job, child=True)
            job = self._create(job, child=False)
        for check in range(self.config.max_poll_checks):
            if job.phase != "processing":
                break
            job = self._status(job)
            if job.last_status == "PUBLISHED":
                raise GraphReconciliationRequired(
                    "HUMAN: container is published but media ID is unknown"
                )
            if job.phase == "processing" and check + 1 < self.config.max_poll_checks:
                self.sleep(self.config.poll_interval_s)
        if job.phase in {"error", "expired"}:
            raise GraphContainerError("Container is terminal: " + job.phase)
        if job.phase == "processing":
            raise GraphPendingError("Container still processing; retry resumes the existing ID")
        # A resumed known-rejected publish may now be PUBLISHED: never repeat it blindly.
        job = self._status(job)
        if job.last_status != "FINISHED":
            raise GraphReconciliationRequired("HUMAN: container is no longer ready to publish")

        def check_quota(post: Post, approval: Approval, current: GraphJob) -> GraphJob:
            if self.verifier is None or post.media_manifest is None:
                raise LiveConfigurationError("A media verifier and approved manifest are mandatory")
            self.verifier.verify(post.media_manifest, self.config)
            self._quota()
            return current

        job = self._step(job, check_quota)
        job = self._intent(job, "publishing")
        rejection: GraphAPIError | None = None

        def publish_remote(post: Post, approval: Approval, current: GraphJob) -> GraphJob:
            nonlocal rejection
            if current.phase != "publishing":
                raise GraphPendingError("Operation advanced concurrently")
            try:
                media_id = self._id(
                    graph_request(
                        self.transport,
                        "POST",
                        f"/{self.account_id}/media_publish",
                        {"creation_id": str(current.container_id)},
                    )
                )
            except GraphAPIError as error:
                rejection = error
                return current.model_copy(update={"phase": "ready"})
            return current.model_copy(
                update={"phase": "published", "media_id": media_id, "approval_id": approval.id}
            )

        job = self._step(job, publish_remote)
        if rejection:
            raise rejection
        return self.store.finish(job.id, self.config, self.account_id)
