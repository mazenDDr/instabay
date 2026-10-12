"""FR-09, FR-10: reference previews cannot be relabeled as live ads or falsely scored."""

import pytest
from pydantic import ValidationError

from instabay.adapters.graph_models import MediaValidationError
from instabay.content.evidence import EvidenceCopyContext
from instabay.core.schemas import EvidenceAttachment, Post, Review, canonical_hash
from instabay.repository import Repository
from tests.graph_support import live_post, publisher
from tests.unit.test_content_evidence import campaign, selection


def test_attaching_a_live_manifest_does_not_erase_reference_source_scope(tmp_path):
    repo = Repository(tmp_path / "state.sqlite")
    post = live_post(repo)
    _, proof, _, slots = campaign()
    selected = selection(slots[0])
    context = EvidenceCopyContext(
        selection=selected,
        property_name=proof.property_name,
        geography=proof.geography,
        source_date_note=proof.source_date_note,
        facts=[f for f in proof.facts if f.id in selected.fact_ids],
    )
    data = post.model_dump()
    data["brief"] = selected.brief.model_dump()
    data["evidence"] = EvidenceAttachment(
        context=context.model_dump(mode="json"), context_hash=canonical_hash(context)
    ).model_dump()
    source_post = Post.model_validate(data)
    backend, transport = publisher(repo, "finished")
    with pytest.raises(MediaValidationError, match="Reference campaign"):
        backend._payload(source_post)
    assert not transport.calls
    repo.close()


def test_human_pending_review_cannot_claim_clearance_or_a_judge_score(tmp_path):
    repo = Repository(tmp_path / "state.sqlite")
    post = live_post(repo)
    data = repo.review(post.id).model_dump()
    data.update(check_path="human_pending", judge=None, flagged=False)
    with pytest.raises(ValidationError, match="review flag"):
        Review.model_validate(data)
    data.update(flagged=True, judge=repo.review(post.id).judge.model_dump())
    with pytest.raises(ValidationError, match="invent a score"):
        Review.model_validate(data)
    repo.close()
