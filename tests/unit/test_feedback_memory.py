"""FR-04, FR-09: rejection reasons and caption edits become writer notes; nothing retrains."""

import json
from datetime import date
from pathlib import Path

from instabay.adapters.cassette import RecordingLLMClient
from instabay.adapters.fake_llm import FakeLLM
from instabay.content.feedback import OwnerFeedback, collect, for_writers
from instabay.content.production import generate_week
from instabay.core.schemas import ApprovalRequest
from instabay.llm import RunBudget
from tests.integration.test_production_generation import freeze_test_brand
from tests.integration.test_week import request, week
from tests.unit.test_content_evidence import ROOT, campaign


def test_lessons_come_from_latest_rejections_and_edits(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    with week(tmp_path) as runner:
        posts = runner.start(request()).post_ids
        repo = runner.repository
        rejected, edited, undone = posts[0], posts[1], posts[2]
        repo.approve(
            rejected,
            ApprovalRequest(
                decision="REJECTED", actor="Owner", reason="Too salesy", seconds_spent=1
            ),
        )
        new_en = repo.post(edited).en.caption.replace("\n", " ", 1) + "\nCalm by the water."
        repo.approve(
            edited,
            ApprovalRequest(decision="EDITED", actor="Owner", en_caption=new_en, seconds_spent=1),
        )
        repo.approve(
            undone,
            ApprovalRequest(
                decision="REJECTED", actor="Owner", reason="Wrong pool", seconds_spent=1
            ),
        )
        repo.approve(undone, ApprovalRequest(decision="REVOKED", actor="Owner", seconds_spent=1))
    lessons = collect([db])
    kinds = {(x.kind, x.language) for x in lessons}
    assert ("rejected", "both") in kinds and ("edited", "en") in kinds
    assert not any("Wrong pool" in x.text for x in lessons), "an undone rejection is no lesson"
    feedback = for_writers(lessons)
    assert any("Too salesy" in a for a in feedback.avoid)
    assert any("Calm by the water." in p for p in feedback.prefer_en) and not feedback.prefer_ar
    reject_id = next(x.id for x in lessons if x.kind == "rejected")
    assert all(x.id != reject_id for x in collect([db], {reject_id}))


def test_writers_receive_owner_feedback_in_their_requests(tmp_path: Path) -> None:
    brand, evidence, catalog, _ = campaign()
    output = tmp_path / "out"
    freeze_test_brand(output, brand)
    feedback = OwnerFeedback(
        avoid=["Rejected a photo (spa): no rhetorical questions"], prefer_en=["“A” → “B”"]
    )
    recording = RecordingLLMClient(FakeLLM(ROOT / "tests/fixtures/llm"), output / "cassette.json")
    try:
        generate_week(
            brand=brand,
            evidence=evidence,
            catalog=catalog,
            root=ROOT,
            output=output,
            run_id="reference-w42",
            week_start=date(2026, 10, 12),
            model="fake-fixture-v1",
            client=recording,
            budget=RunBudget(max_tokens=100000),
            draft_only=True,
            feedback=feedback,
        )
    finally:
        recording.close()
    tape = json.loads((output / "cassette.json").read_text())["entries"]
    by_template = {e["request"]["template_name"]: e["request"]["inputs"] for e in tape}
    assert by_template["visual_brief"]["owner_feedback"] == {"avoid": feedback.avoid}
    assert by_template["grounded_copy_en"]["owner_feedback"]["prefer"] == ["“A” → “B”"]
    assert by_template["grounded_copy_ar"]["owner_feedback"] == {
        "avoid": feedback.avoid,
        "prefer": [],
    }
