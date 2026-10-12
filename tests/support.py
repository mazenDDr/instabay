"""NFR-07: shared offline domain factories, with clearly synthetic human decisions."""

import json
from datetime import date
from pathlib import Path

from instabay.core.hashtags import select_hashtags
from instabay.core.planner import plan_week
from instabay.core.schemas import (
    BrandConstitution,
    Brief,
    Copy,
    JudgeResult,
    JudgeSample,
    Post,
    Review,
    RubricScores,
    RuleResult,
    WorkflowInput,
)
from instabay.repository import Repository


def demo_brand() -> BrandConstitution:
    payload = json.loads(Path("tests/fixtures/llm/brand_architect__brand-draft.json").read_text())
    return BrandConstitution.model_validate(payload["response"])


def draft_post(repository: Repository) -> Post:
    brand = demo_brand()
    digest = repository.register_brand(brand)
    request = WorkflowInput(run_id="2026-w42", week_start=date(2026, 10, 12))
    repository.start_run(request, digest)
    slots = plan_week(brand, digest, request.run_id, request.week_start)
    repository.save_slots(slots)
    slot = slots[0]
    post = Post(
        id=slot.id,
        slot_id=slot.id,
        brand_hash=digest,
        format=slot.arm.format,
        brief=Brief(
            angle="quiet",
            hook="number",
            key_message="A slower moment",
            visual_description="Terracotta arches and palms",
            photo_uri="reference.jpg",
            cta="save",
            must_not=["unverified claims"],
        ),
        en=Copy(
            caption="Three reasons to slow down: light, shade, quiet.", alt_text="Arches and palms"
        ),
        ar=Copy(caption="ثلاث لحظات على مهل: ضوء، وظلال، وهدوء.", alt_text="أقواس ونخيل"),
        hashtags=select_hashtags(brand),
        prompt_hashes={"copy_en": "a" * 64, "copy_ar": "b" * 64},
    )
    repository.save_post(post)
    save_review(repository, post)
    return post


def save_review(repository: Repository, post: Post, *, flagged: bool = False) -> None:
    sample = JudgeSample(
        scores=RubricScores(
            voice=5, pillar_fit=5, caption_visual_match=4, hashtag_policy=5, format_cta=4
        ),
        fixes=[],
    )
    repository.save_review(
        Review(
            post_id=post.id,
            content_hash=post.content_hash,
            rules=RuleResult(
                post_id=post.id,
                content_hash=post.content_hash,
                passed=True,
                violations=[],
                arabic_ratio=1,
            ),
            judge=JudgeResult(
                content_hash=post.content_hash,
                samples=[sample] * 3,
                average=4.6,
                passed=True,
                fixes=[],
            ),
            flagged=flagged,
            flags=["Synthetic review flag"] if flagged else [],
        )
    )
