"""FR-01 to FR-09: bounded planning, claims, native Arabic checks and approval edits."""

from datetime import date
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from sqlmodel import Session, select

from instabay.adapters.memory_outbox import MemoryOutbox
from instabay.adapters.publisher import DryRunPublisher, FileOutboxWriter
from instabay.core.hashtags import select_hashtags
from instabay.core.planner import plan_week
from instabay.core.rules import arabic_script_ratio, check_rules
from instabay.core.schemas import (
    ApprovalRequest,
    BrandConstitution,
    Copy,
    PlanningPreferences,
    Post,
    WorkflowInput,
)
from instabay.core.tables import ApprovalRow, SlotRow
from instabay.repository import Repository
from tests.support import demo_brand, draft_post, save_review


@given(
    st.dictionaries(
        st.sampled_from(["underwater", "spa", "guests", "local", "offers"]),
        st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
    )
)
@settings(max_examples=50, database=None)
def test_planner_respects_limits_for_arbitrary_preferences(scores: dict[str, float]) -> None:
    brand = demo_brand()
    plan = plan_week(
        brand,
        "a" * 64,
        "property",
        date(2026, 10, 12),
        PlanningPreferences(pillar=scores, format={"photo": 100, "reel": -100}),
    )
    assert len(plan) == 7
    for pillar in brand.pillars:
        share = sum(slot.arm.pillar == pillar.id for slot in plan) / 7
        assert pillar.min_share <= share <= pillar.max_share
    assert sum(slot.arm.format == "reel" for slot in plan) >= 1
    assert any(slot.explore for slot in plan)
    assert all(not 1 <= slot.scheduled_at.hour < 7 for slot in plan)
    assert all(str(slot.scheduled_at.tzinfo) == "Africa/Cairo" for slot in plan)
    assert plan == plan_week(
        brand,
        "a" * 64,
        "property",
        date(2026, 10, 12),
        PlanningPreferences(pillar=scores, format={"photo": 100, "reel": -100}),
    )


def test_infeasible_integer_pillar_bounds_are_rejected() -> None:
    data = demo_brand().model_dump()
    for pillar in data["pillars"]:
        pillar["min_share"], pillar["max_share"] = 0.2, 0.2
    with pytest.raises(ValidationError, match="integer"):
        BrandConstitution.model_validate(data)


def test_naive_or_quiet_schedule_is_rejected() -> None:
    from instabay.core.schemas import Slot

    slot = plan_week(demo_brand(), "a" * 64, "clock", date(2026, 10, 12))[0]
    for clock in ["2026-10-12T12:00:00", "2026-10-12T03:00:00+03:00"]:
        with pytest.raises(ValidationError):
            Slot.model_validate({**slot.model_dump(), "scheduled_at": clock})


def test_hashtag_selection_is_unique_bounded_and_branded() -> None:
    brand = demo_brand()
    tags = select_hashtags(brand)
    assert 8 <= len(tags) <= 15
    assert len(tags) == len(set(tags))
    assert set(tags) & set(brand.hashtags.branded)
    with pytest.raises(ValueError):
        select_hashtags(brand, 30)


@pytest.mark.parametrize(
    "caption, violation",
    [
        ("Enjoy our infinity pool", "facility"),
        ("Only $99 tonight", "offer"),
        ("BUY NOW", "banned"),
        ("Quiet. 🐠🐠🐠", "emoji"),
        (" ".join(f"@guest{number}" for number in range(21)), "mentions"),
        ("x" * 2180, "2200"),
    ],
)
def test_rules_explain_caption_failures(tmp_path: Path, caption: str, violation: str) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    changed = Post.model_validate(
        {**post.model_dump(), "en": Copy(caption=caption, alt_text="Arches")}
    )
    result = check_rules(changed, demo_brand())
    assert not result.passed
    assert any(violation in message for message in result.violations)


def test_arabic_ratio_ignores_latin_hashtags_but_not_english_copy() -> None:
    assert arabic_script_ratio("صباح على مهل #InstaBay @guest") == 1
    assert arabic_script_ratio("Quiet mornings and palm shadows") == 0
    assert arabic_script_ratio("123 🐠") == 0


def test_offer_id_cannot_legitimize_unregistered_prices(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    changed = Post.model_validate(
        {
            **post.model_dump(),
            "offer_id": "made-up",
            "en": Copy(caption="Only USD 99", alt_text="Arches"),
        }
    )
    assert not check_rules(changed, demo_brand()).passed


def test_edits_store_diff_and_approve_the_new_snapshot(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    decision = repository.approve(
        post.id,
        ApprovalRequest(
            decision="EDITED",
            actor="test-human",
            reason="Softer CTA",
            en_caption="A slower morning. Save a little quiet.",
            seconds_spent=41,
        ),
    )
    changed = repository.post(post.id)
    assert changed.content_hash != post.content_hash
    assert decision.content_hash == changed.content_hash
    assert "en.caption" in decision.diff
    assert "Save a little quiet" in decision.diff["en.caption"]
    assert decision.seconds_spent == 41
    outbox = MemoryOutbox()
    receipt = DryRunPublisher(repository, writer=outbox).publish(post.id)
    assert receipt.content_hash == changed.content_hash
    assert next(iter(outbox.written.values())).en.caption == changed.en.caption


def test_invalid_human_edit_does_not_mutate_post_or_approval(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    with pytest.raises(ValueError, match="deterministic"):
        repository.approve(
            post.id,
            ApprovalRequest(
                decision="EDITED",
                actor="test-human",
                reason="Test invalid edit",
                ar_caption="This is English",
                seconds_spent=1,
            ),
        )
    assert repository.post(post.id).content_hash == post.content_hash
    assert repository.latest_approval(post.id) is None


def test_latest_rejection_overrides_an_older_approval(tmp_path: Path) -> None:
    from instabay.adapters.storage import UnapprovedPublishError

    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    repository.approve(
        post.id, ApprovalRequest(decision="APPROVED", actor="test-human", seconds_spent=1)
    )
    repository.approve(
        post.id,
        ApprovalRequest(
            decision="REJECTED", actor="test-human", reason="Changed mind", seconds_spent=2
        ),
    )
    with pytest.raises(UnapprovedPublishError):
        DryRunPublisher(repository, writer=MemoryOutbox()).publish(post.id)
    with Session(repository.engine) as session:
        assert len(session.exec(select(ApprovalRow)).all()) == 2


def test_flagged_content_needs_human_reason(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    save_review(repository, post, flagged=True)
    with pytest.raises(ValueError, match="reason"):
        repository.approve(
            post.id, ApprovalRequest(decision="APPROVED", actor="test-human", seconds_spent=1)
        )


def test_writer_failure_rolls_back_receipt_and_retry_is_idempotent(tmp_path: Path) -> None:
    class BrokenWriter:
        def write(self, post: Post, approval: object) -> str:
            raise OSError("Disk unavailable")

    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    repository.approve(
        post.id, ApprovalRequest(decision="APPROVED", actor="test-human", seconds_spent=1)
    )
    with pytest.raises(OSError):
        DryRunPublisher(repository, writer=BrokenWriter()).publish(post.id)
    assert repository.publications("2026-w42") == []
    publisher = DryRunPublisher(repository, tmp_path / "outbox")
    first, second = publisher.publish(post.id), publisher.publish(post.id)
    assert first == second
    assert len(list((tmp_path / "outbox").glob("*.json"))) == 1
    with pytest.raises(ValueError, match="cannot be edited"):
        repository.save_post(Post.model_validate({**post.model_dump(), "revision": 1}))


def test_unapproved_file_publisher_does_not_create_outbox(tmp_path: Path) -> None:
    from instabay.adapters.storage import UnapprovedPublishError

    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    directory = tmp_path / "outbox"
    with pytest.raises(UnapprovedPublishError):
        DryRunPublisher(repository, writer=FileOutboxWriter(directory)).publish(post.id)
    assert not directory.exists()


def test_schedules_are_stored_in_utc_and_draft_brand_cannot_start_real_run(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "db.sqlite")
    post = draft_post(repository)
    with Session(repository.engine) as session:
        assert all(
            row.scheduled_at.endswith("+00:00") for row in session.exec(select(SlotRow)).all()
        )
    with pytest.raises(ValueError, match="human-frozen"):
        repository.start_run(
            WorkflowInput(run_id="real", week_start=date(2026, 10, 12), demo=False), post.brand_hash
        )
    digest = repository.register_brand(demo_brand(), actor="test-human")
    repository.start_run(
        WorkflowInput(run_id="real", week_start=date(2026, 10, 12), demo=False), digest
    )
