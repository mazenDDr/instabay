"""FR-08: three judge requests and one Self-Refine pass; System-1 arrives in Phase 6."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from instabay.agents.common import agent_inputs, prompt_hashes
from instabay.agents.copy_ar import ArabicWriter
from instabay.agents.copy_en import EnglishWriter
from instabay.core.rules import check_rules
from instabay.core.schemas import (
    BrandConstitution,
    Brief,
    Copy,
    JudgeResult,
    JudgeSample,
    Post,
    Review,
    Slot,
)
from instabay.llm import LLMService


def write_bilingual(
    service: LLMService,
    slot: Slot,
    brand: BrandConstitution,
    brief: Brief,
    previous: Post | None = None,
    fixes: list[str] | None = None,
) -> tuple[Copy, Copy]:
    """FR-04: EN/AR provider requests run concurrently from the common brief."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        en = pool.submit(
            EnglishWriter(service).write,
            slot,
            brand,
            brief,
            previous.en if previous else None,
            fixes,
        )
        ar = pool.submit(
            ArabicWriter(service).write,
            slot,
            brand,
            brief,
            previous.ar if previous else None,
            fixes,
        )
        return en.result(), ar.result()


class Judge:
    """FR-08: average scores in code; fake scores are illustrative, not calibrated."""

    def __init__(self, service: LLMService) -> None:
        self.service = service

    def evaluate(self, post: Post, brand: BrandConstitution) -> JudgeResult:
        """FR-08: separate sample identities prevent the cache collapsing three requests."""
        samples = [
            self.service.generate(
                template_name="judge",
                slot_id=post.slot_id,
                inputs=agent_inputs(post=post, brand=brand, sample=index),
                output_type=JudgeSample,
                model="fake-judge-fixture-v1",
                temperature=0,
            )
            for index in range(3)
        ]
        average = sum(sample.scores.average for sample in samples) / 3
        return JudgeResult(
            content_hash=post.content_hash,
            samples=samples,
            average=average,
            passed=average >= brand.judge_threshold,
            fixes=list(dict.fromkeys(fix for sample in samples for fix in sample.fixes)),
        )

    def evaluate_cascade(
        self, post: Post, brand: BrandConstitution, questions: list[str]
    ) -> JudgeResult:
        """FR-08: focus escalation context on flagged questions; retain three rubric samples."""
        language = "ar" if questions and all(q.startswith("ar.") for q in questions) else "en"
        samples = [
            self.service.generate(
                template_name=f"judge_cascade_{language}",
                slot_id=post.slot_id,
                inputs=agent_inputs(
                    post=post, brand=brand, sample=index, escalated_questions=questions
                ),
                output_type=JudgeSample,
                model="fake-judge-fixture-v1",
                temperature=0,
            )
            for index in range(3)
        ]
        average = sum(sample.scores.average for sample in samples) / 3
        return JudgeResult(
            content_hash=post.content_hash,
            samples=samples,
            average=average,
            passed=average >= brand.judge_threshold,
            fixes=list(dict.fromkeys(fix for sample in samples for fix in sample.fixes)),
        )

    def check_and_refine(
        self,
        post: Post,
        slot: Slot,
        brand: BrandConstitution,
        record_initial: Callable[[Review], None] | None = None,
    ) -> tuple[Post, Review]:
        """FR-08: rules first, one revision at most, then flag remaining failures to a human."""
        rules = check_rules(post, brand)
        result = self.evaluate(post, brand)
        if record_initial is not None:
            initial_flags = list(rules.violations)
            if not result.passed:
                initial_flags.append("Judge score below brand threshold before revision")
            if post.media_status == "concept_only":
                initial_flags.append("Reel concept only: no video has been rendered")
            record_initial(
                Review(
                    post_id=post.id,
                    content_hash=post.content_hash,
                    rules=rules,
                    judge=result,
                    flagged=bool(initial_flags),
                    flags=initial_flags,
                )
            )
        if (not rules.passed or not result.passed) and post.revision == 0:
            fixes = rules.violations + result.fixes
            en, ar = write_bilingual(
                self.service, slot, brand, post.brief, previous=post, fixes=fixes
            )
            hashes = {
                **post.prompt_hashes,
                **prompt_hashes(self.service, ["copy_en_revision", "copy_ar_revision"]),
            }
            post = Post.model_validate(
                {
                    **post.model_dump(),
                    "en": en,
                    "ar": ar,
                    "revision": post.revision + 1,
                    "prompt_hashes": hashes,
                }
            )
            rules, result = check_rules(post, brand), self.evaluate(post, brand)
        flags = list(rules.violations)
        if not result.passed:
            flags.append("Judge score below brand threshold after one revision")
        if post.media_status == "concept_only":
            flags.append("Reel concept only: no video has been rendered")
        return post, Review(
            post_id=post.id,
            content_hash=post.content_hash,
            rules=rules,
            judge=result,
            flagged=bool(flags),
            flags=flags,
        )
