"""FR-01 to FR-10: validated SQLModel storage and transactional approval enforcement."""

import difflib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event
from sqlmodel import Session, SQLModel, col, create_engine, select

from instabay.adapters.storage import OutboxWriter, UnapprovedPublishError
from instabay.core.rules import check_rules
from instabay.core.schemas import (
    Approval,
    ApprovalRequest,
    Arm,
    BrandConstitution,
    Brief,
    Copy,
    JudgeResult,
    JudgeSample,
    Post,
    Publication,
    Review,
    RubricScores,
    RuleResult,
    Slot,
    WorkflowInput,
    canonical_hash,
)
from instabay.core.tables import (
    ApprovalRow,
    ArmRow,
    BrandVersionRow,
    HashtagRow,
    JudgeScoreRow,
    PostRow,
    PublicationRow,
    ReviewRow,
    RunRow,
    SlotRow,
)


class Repository:
    """FR-09: publish snapshots are authorized inside a SQLite write transaction."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", self._enable_foreign_keys)
        SQLModel.metadata.create_all(self.engine)

    @staticmethod
    def _enable_foreign_keys(connection: sqlite3.Connection, record: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")

    def register_brand(self, brand: BrandConstitution, *, actor: str | None = None) -> str:
        """FR-01: only an explicit human actor freezes a brand; graph demos pass none."""
        brand = BrandConstitution.model_validate(brand.model_dump())
        digest = canonical_hash(brand)
        with Session(self.engine) as session:
            row = session.get(BrandVersionRow, digest)
            if row is None:
                row = BrandVersionRow(hash=digest, constitution_json=brand.model_dump_json())
            if actor is not None:
                if not actor.strip():
                    raise ValueError("Freezing requires a human actor")
                row.frozen, row.actor = True, actor
                row.frozen_at = datetime.now(UTC).isoformat()
            session.add(row)
            session.commit()
        return digest

    def brand(self, digest: str) -> BrandConstitution:
        """FR-01: validate the stored constitution before every use."""
        with Session(self.engine) as session:
            row = session.get(BrandVersionRow, digest)
            if row is None:
                raise KeyError("Unknown brand version")
            return BrandConstitution.model_validate_json(row.constitution_json)

    def start_run(self, request: WorkflowInput, brand_hash: str) -> None:
        """FR-01: real runs require a frozen brand; fixture demos are explicitly marked."""
        with Session(self.engine) as session:
            brand = session.get(BrandVersionRow, brand_hash)
            if brand is None or (not request.demo and not brand.frozen):
                raise ValueError("A non-demo run requires a human-frozen brand")
            row = RunRow(
                id=request.run_id,
                week_start=request.week_start.isoformat(),
                brand_hash=brand_hash,
                demo=request.demo,
            )
            existing = session.get(RunRow, request.run_id)
            if existing and existing.model_dump() != row.model_dump():
                raise ValueError("Run identity already belongs to different inputs")
            if existing is None:
                session.add(row)
                session.commit()

    def run(self, run_id: str) -> WorkflowInput:
        """FR-03: recover a validated run after a process restart."""
        with Session(self.engine) as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError("Unknown run")
            return WorkflowInput.model_validate(
                {"run_id": row.id, "week_start": row.week_start, "demo": row.demo}
            )

    def save_slots(self, slots: list[Slot]) -> None:
        """FR-03: store arms once and UTC schedule rows separately."""
        with Session(self.engine) as session:
            for slot in slots:
                run = session.get(RunRow, slot.run_id)
                if run is None or run.brand_hash != slot.brand_hash:
                    raise ValueError("Slot must match its stored run and brand")
                arm = slot.arm
                if session.get(ArmRow, arm.id) is None:
                    session.add(ArmRow(id=arm.id, **arm.model_dump()))
                    session.flush()
                row = SlotRow(
                    id=slot.id,
                    run_id=slot.run_id,
                    arm_id=arm.id,
                    scheduled_at=slot.scheduled_at.astimezone(UTC).isoformat(),
                    segment=slot.segment,
                    explore=slot.explore,
                )
                existing = session.get(SlotRow, slot.id)
                if existing and existing.model_dump() != row.model_dump():
                    raise ValueError("Slot identity already belongs to another plan")
                if existing is None:
                    session.add(row)
            session.commit()

    def slots(self, run_id: str) -> list[Slot]:
        """FR-03: validate persisted arms and convert UTC schedules to Cairo."""
        with Session(self.engine) as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise KeyError("Unknown run")
            rows = session.exec(
                select(SlotRow).where(SlotRow.run_id == run_id).order_by(col(SlotRow.scheduled_at))
            ).all()
            result = []
            for row in rows:
                arm = session.get(ArmRow, row.arm_id)
                if arm is None:
                    raise ValueError("Broken slot/arm relationship")
                result.append(
                    Slot.model_validate(
                        {
                            "id": row.id,
                            "run_id": row.run_id,
                            "brand_hash": run.brand_hash,
                            "scheduled_at": row.scheduled_at,
                            "arm": Arm.model_validate(arm.model_dump(exclude={"id"})),
                            "segment": row.segment,
                            "explore": row.explore,
                        }
                    )
                )
            return result

    def save_post(self, post: Post) -> None:
        """FR-04: revisions invalidate prior approval by changing the content hash."""
        post = Post.model_validate(post.model_dump())
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            self._save_post(session, post)
            session.commit()

    def _save_post(self, session: Session, post: Post) -> None:
        slot = session.get(SlotRow, post.slot_id)
        run = session.get(RunRow, slot.run_id) if slot else None
        if slot is None or run is None or run.brand_hash != post.brand_hash:
            raise ValueError("Post must refer to its stored slot and brand")
        arm = session.get(ArmRow, slot.arm_id)
        if arm is None or arm.format != post.format:
            raise ValueError("Post format must match its planned arm")
        if session.exec(select(PublicationRow).where(PublicationRow.post_id == post.id)).first():
            if self._post(session, post.id).content_hash != post.content_hash:
                raise ValueError("Published snapshots cannot be edited")
            return
        row = PostRow(
            id=post.id,
            slot_id=post.slot_id,
            brief_json=post.brief.model_dump_json(),
            en_caption=post.en.caption,
            en_alt_text=post.en.alt_text,
            ar_caption=post.ar.caption,
            ar_alt_text=post.ar.alt_text,
            prompt_hashes_json=json.dumps(post.prompt_hashes),
            revision=post.revision,
            ai_disclosure=post.ai_disclosure,
            offer_id=post.offer_id,
            media_path=post.media_path,
            media_status=post.media_status,
            idempotency_key=post.idempotency_key,
        )
        session.merge(row)
        session.flush()
        tags = session.exec(select(HashtagRow).where(HashtagRow.post_id == post.id)).all()
        for tag in tags:
            session.delete(tag)
        session.flush()
        for index, tag_text in enumerate(post.hashtags):
            session.add(HashtagRow(post_id=post.id, position=index, tag=tag_text))

    def _post(self, session: Session, post_id: str) -> Post:
        row = session.get(PostRow, post_id)
        if row is None:
            raise KeyError("Unknown post")
        slot = session.get(SlotRow, row.slot_id)
        if slot is None:
            raise ValueError("Broken post/slot relationship")
        arm = session.get(ArmRow, slot.arm_id)
        if arm is None:
            raise ValueError("Broken slot/arm relationship")
        run = session.get(RunRow, slot.run_id)
        if run is None:
            raise ValueError("Broken slot/run relationship")
        tags = session.exec(
            select(HashtagRow)
            .where(HashtagRow.post_id == row.id)
            .order_by(col(HashtagRow.position))
        ).all()
        return Post.model_validate(
            {
                "id": row.id,
                "slot_id": row.slot_id,
                "brand_hash": run.brand_hash,
                "format": arm.format,
                "brief": Brief.model_validate_json(row.brief_json),
                "en": Copy(caption=row.en_caption, alt_text=row.en_alt_text),
                "ar": Copy(caption=row.ar_caption, alt_text=row.ar_alt_text),
                "hashtags": [tag.tag for tag in tags],
                "prompt_hashes": json.loads(row.prompt_hashes_json),
                "revision": row.revision,
                "ai_disclosure": row.ai_disclosure,
                "offer_id": row.offer_id,
                "media_path": row.media_path,
                "media_status": row.media_status,
            }
        )

    def post(self, post_id: str) -> Post:
        """FR-04: retrieve a fully validated content snapshot."""
        with Session(self.engine) as session:
            return self._post(session, post_id)

    def post_ids(self, run_id: str) -> list[str]:
        """FR-09: preserve the plan's order in the human queue."""
        with Session(self.engine) as session:
            result = []
            for slot in self.slots(run_id):
                post = session.exec(select(PostRow).where(PostRow.slot_id == slot.id)).first()
                if post is not None:
                    result.append(post.id)
            return result

    def save_review(self, review: Review) -> None:
        """FR-08: retain each judge sample and deterministic rule details."""
        with Session(self.engine) as session:
            if self._post(session, review.post_id).content_hash != review.content_hash:
                raise ValueError("Review does not match the current post")
            for index, sample in enumerate(review.judge.samples):
                session.merge(
                    JudgeScoreRow(
                        post_id=review.post_id,
                        content_hash=review.content_hash,
                        sample=index,
                        **sample.scores.model_dump(),
                        fixes_json=json.dumps(sample.fixes),
                    )
                )
            session.merge(
                ReviewRow(
                    post_id=review.post_id,
                    content_hash=review.content_hash,
                    rules_passed=review.rules.passed,
                    violations_json=json.dumps(review.rules.violations),
                    arabic_ratio=review.rules.arabic_ratio,
                    flags_json=json.dumps(review.flags),
                )
            )
            session.commit()

    def review(self, post_id: str) -> Review:
        """FR-08: aggregate stored samples in code instead of trusting an LLM average."""
        with Session(self.engine) as session:
            row = session.get(ReviewRow, post_id)
            post = self._post(session, post_id)
            if row is None or row.content_hash != post.content_hash:
                raise ValueError("Post needs current checks before human approval")
            scores = session.exec(
                select(JudgeScoreRow)
                .where(
                    JudgeScoreRow.post_id == post_id, JudgeScoreRow.content_hash == row.content_hash
                )
                .order_by(col(JudgeScoreRow.sample))
            ).all()
            samples = [
                JudgeSample(
                    scores=RubricScores.model_validate(
                        score.model_dump(
                            exclude={"post_id", "content_hash", "sample", "fixes_json"}
                        )
                    ),
                    fixes=json.loads(score.fixes_json),
                )
                for score in scores
            ]
            if len(samples) != 3:
                raise ValueError("Exactly three judge samples are required")
            average = sum(sample.scores.average for sample in samples) / 3
            brand_row = session.get(BrandVersionRow, post.brand_hash)
            if brand_row is None:
                raise ValueError("Unknown brand version")
            brand = BrandConstitution.model_validate_json(brand_row.constitution_json)
            rules = RuleResult(
                post_id=post_id,
                content_hash=row.content_hash,
                passed=row.rules_passed,
                violations=json.loads(row.violations_json),
                arabic_ratio=row.arabic_ratio,
            )
            judge = JudgeResult(
                content_hash=row.content_hash,
                samples=samples,
                average=average,
                passed=average >= brand.judge_threshold,
                fixes=list(dict.fromkeys(fix for sample in samples for fix in sample.fixes)),
            )
            flags = json.loads(row.flags_json)
            return Review(
                post_id=post_id,
                content_hash=row.content_hash,
                rules=rules,
                judge=judge,
                flagged=bool(flags),
                flags=flags,
            )

    @staticmethod
    def _approval(row: ApprovalRow) -> Approval:
        return Approval.model_validate(
            {**row.model_dump(exclude={"sequence", "diff_json"}), "diff": json.loads(row.diff_json)}
        )

    def latest_approval(self, post_id: str) -> Approval | None:
        """FR-09: the most recent stored decision wins, including rejection."""
        with Session(self.engine) as session:
            row = self._latest_approval(session, post_id)
            return self._approval(row) if row else None

    @staticmethod
    def _latest_approval(session: Session, post_id: str) -> ApprovalRow | None:
        return session.exec(
            select(ApprovalRow)
            .where(ApprovalRow.post_id == post_id)
            .order_by(col(ApprovalRow.sequence).desc())
        ).first()

    def approve(self, post_id: str, request: ApprovalRequest) -> Approval:
        """FR-09: store timed decisions and caption diffs in the same revision transaction."""
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            post = self._post(session, post_id)
            row = session.get(ReviewRow, post_id)
            if request.decision != "REJECTED" and (
                row is None or row.content_hash != post.content_hash
            ):
                raise ValueError("Post needs current checks before approval")
            if row is not None and json.loads(row.flags_json) and not request.reason.strip():
                raise ValueError("Flagged posts need an explicit human reason")
            diff = {}
            if request.decision == "EDITED":
                before = post
                en = Copy(caption=request.en_caption or post.en.caption, alt_text=post.en.alt_text)
                ar = Copy(caption=request.ar_caption or post.ar.caption, alt_text=post.ar.alt_text)
                post = Post.model_validate(
                    {**post.model_dump(), "en": en, "ar": ar, "revision": post.revision + 1}
                )
                for language in ("en", "ar"):
                    old, new = getattr(before, language).caption, getattr(post, language).caption
                    if old != new:
                        diff[f"{language}.caption"] = "\n".join(
                            difflib.unified_diff(
                                old.splitlines(),
                                new.splitlines(),
                                fromfile="before",
                                tofile="after",
                                lineterm="",
                            )
                        )
                if not diff:
                    raise ValueError("EDITED decision must actually change a caption")
                self._check_content(session, post)
                self._save_post(session, post)
            elif request.decision == "APPROVED":
                self._check_content(session, post)
            approval = Approval(
                id=str(uuid4()),
                post_id=post_id,
                content_hash=post.content_hash,
                decision=request.decision,
                actor=request.actor,
                reason=request.reason,
                diff=diff,
                seconds_spent=request.seconds_spent,
                decided_at=datetime.now(UTC),
            )
            session.add(
                ApprovalRow(
                    **approval.model_dump(mode="json", exclude={"diff"}),
                    diff_json=json.dumps(approval.diff),
                )
            )
            session.commit()
            return approval

    def publish_approved(self, post_id: str, writer: OutboxWriter) -> Publication:
        """FR-09: approve exact content before any I/O; BEGIN IMMEDIATE prevents edit races."""
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            post = self._post(session, post_id)
            row = self._latest_approval(session, post_id)
            if (
                row is None
                or row.decision not in {"APPROVED", "EDITED"}
                or row.content_hash != post.content_hash
            ):
                raise UnapprovedPublishError(
                    "Publishing requires a matching stored APPROVED/EDITED decision"
                )
            self._check_content(session, post)
            existing = session.exec(
                select(PublicationRow).where(PublicationRow.post_id == post_id)
            ).first()
            if existing:
                return Publication.model_validate(existing.model_dump())
            approval = self._approval(row)
            location = writer.write(post, approval)
            publication = Publication(
                id=str(uuid4()),
                post_id=post_id,
                approval_id=approval.id,
                idempotency_key=post.idempotency_key,
                content_hash=post.content_hash,
                outbox_path=location,
                published_at=datetime.now(UTC),
            )
            session.add(PublicationRow(**publication.model_dump(mode="json")))
            session.commit()
            return publication

    @staticmethod
    def _check_content(session: Session, post: Post) -> None:
        brand = session.get(BrandVersionRow, post.brand_hash)
        if brand is None:
            raise ValueError("Unknown brand version")
        rules = check_rules(post, BrandConstitution.model_validate_json(brand.constitution_json))
        if not rules.passed:
            raise ValueError("Content violates deterministic rules: " + "; ".join(rules.violations))

    def publications(self, run_id: str) -> list[Publication]:
        """FR-10: collect dry-run receipts without claiming live Instagram publication."""
        ids = self.post_ids(run_id)
        with Session(self.engine) as session:
            rows = session.exec(
                select(PublicationRow).where(col(PublicationRow.post_id).in_(ids))
            ).all()
            return [Publication.model_validate(row.model_dump()) for row in rows]

    def close(self) -> None:
        """NFR-06: release pooled SQLite connections when a command completes."""
        self.engine.dispose()
