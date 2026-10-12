"""FR-08: rules, calibrated atomic checks, selective escalation and reproducible audit routing."""

from collections.abc import Callable
from typing import cast

from pydantic import JsonValue

from instabay.agents.common import prompt_hashes
from instabay.agents.judge import Judge, write_bilingual
from instabay.core.rules import check_rules
from instabay.core.schemas import (
    Boundary,
    BrandConstitution,
    Hash,
    Post,
    Review,
    Slot,
    canonical_hash,
)
from instabay.decisions.calibration import CalibrationProfile
from instabay.decisions.engine import LANGUAGES, Answer, DecisionEngine, Language, normalize_answers
from instabay.decisions.questions import acceptable, decision_state, questions_for
from instabay.video.review import media_flags


class DecisionRecord(Boundary):
    """FR-08: exact raw answer, scoped confidence and explicit reason for escalation."""

    language: Language
    question_id: str
    question_hash: Hash
    answer: Answer | None = None
    calibrated_confidence: float | None = None
    escalated: bool = True
    reason: str
    acceptable: bool = False


class DecisionTrace(Boundary):
    """FR-08, NFR-03: no text or credentials; bind stages to content, engine and calibration."""

    content_hash: Hash
    engine_id: str
    profile_hash: Hash | None = None
    audited: bool = False
    records: list[DecisionRecord]
    judge_questions: list[str]
    judge_called: bool = True
    passed_system1: bool = False


def audit_selected(post: Post, seed: int, rate: float = 0.1) -> bool:
    """NFR-03: stable per snapshot and seed; independent of retry timing."""
    if not 0 <= rate <= 1:
        raise ValueError("Audit rate must be a probability")
    return (
        int(canonical_hash({"post": post.content_hash, "seed": seed, "audit": "v1"}), 16) / 2**256
        < rate
    )


class CheckCascade:
    """FR-08: uncalibrated, unavailable or adverse decisions escalate; never creates approval."""

    def __init__(
        self,
        judge: Judge,
        engine: DecisionEngine | None = None,
        profile: CalibrationProfile | None = None,
        *,
        allow_synthetic: bool = False,
        audit_seed: int = 7,
        audit_rate: float = 0.1,
    ) -> None:
        self.judge, self.engine, self.profile = judge, engine, profile
        self.allow_synthetic, self.audit_seed, self.audit_rate = (
            allow_synthetic,
            audit_seed,
            audit_rate,
        )

    def check(self, post: Post, slot: Slot, brand: BrandConstitution) -> Review:
        """FR-08: rules precede the engine; uncalibrated decisions retain the judge path."""
        rules = check_rules(post, brand)
        records = []
        escalated = []
        adverse = []
        audited = audit_selected(post, self.audit_seed, self.audit_rate)
        if self.engine is not None and rules.passed:
            for lang in LANGUAGES:
                language = lang
                questions = questions_for(brand, lang)
                answers = {}
                error = ""
                try:
                    answers = self.engine.decide(
                        cast(dict[str, JsonValue], decision_state(post, brand, lang)), questions
                    )
                    # Do not trust a Protocol implementation to bypass boundary validation.
                    answers = normalize_answers(
                        {"answers": {k: v.model_dump() for k, v in answers.items()}}, questions
                    )
                except (ValueError, RuntimeError, OSError):
                    error = "engine_unavailable_or_invalid"
                for qid, question in questions.items():
                    answer = answers.get(qid)
                    confidence = None
                    if answer is not None and self.profile is not None:
                        confidence = self.profile.confidence(
                            answer,
                            qid,
                            lang,
                            question.hash,
                            engine_id=self.engine.engine_id,
                            brand_hash=post.brand_hash,
                            synthetic_engine=self.engine.synthetic,
                            allow_synthetic=self.allow_synthetic,
                        )
                    allowed = answer is not None and acceptable(answer, qid, slot, brand, lang)
                    reason = error or (
                        "uncalibrated_or_abstained"
                        if confidence is None
                        else "adverse_answer"
                        if not allowed
                        else "audit"
                        if audited
                        else "accepted"
                    )
                    needs_judge = bool(error) or confidence is None or not allowed or audited
                    if confidence is not None and not allowed:
                        adverse.append(
                            f"{language}.{qid}: does not satisfy the planned/brand policy"
                        )
                    if needs_judge:
                        escalated.append(f"{language}.{qid}")
                    records.append(
                        DecisionRecord(
                            language=lang,
                            question_id=qid,
                            question_hash=question.hash,
                            answer=answer,
                            calibrated_confidence=confidence,
                            escalated=needs_judge,
                            reason=reason,
                            acceptable=allowed,
                        )
                    )
        else:
            escalated = ["rules" if not rules.passed else "system1_not_configured"]
        fast_pass = bool(records) and not escalated and rules.passed
        trace = DecisionTrace(
            content_hash=post.content_hash,
            engine_id=self.engine.engine_id if self.engine else "judge-only",
            profile_hash=self.profile.hash if self.profile else None,
            audited=audited,
            records=records,
            judge_questions=escalated,
            judge_called=not fast_pass,
            passed_system1=fast_pass,
        )
        result = (
            None
            if fast_pass
            else (
                self.judge.evaluate_cascade(post, brand, escalated)
                if self.engine
                else self.judge.evaluate(post, brand)
            )
        )
        flags = [*rules.violations, *adverse]
        if result is not None and not result.passed:
            flags.append("Judge score below brand threshold")
        flags.extend(media_flags(post))
        return Review(
            post_id=post.id,
            content_hash=post.content_hash,
            rules=rules,
            judge=result,
            check_path="system1" if fast_pass else "judge",
            decision_trace=cast(dict[str, JsonValue], trace.model_dump(mode="json")),
            flagged=bool(flags),
            flags=flags,
        )

    def check_and_refine(
        self,
        post: Post,
        slot: Slot,
        brand: BrandConstitution,
        record_initial: Callable[[Review], None] | None = None,
    ) -> tuple[Post, Review]:
        """FR-08: at most one refinement; recheck every changed snapshot."""
        if self.engine is None:
            return self.judge.check_and_refine(post, slot, brand, record_initial)
        review = self.check(post, slot, brand)
        if record_initial:
            record_initial(review)
        failures = [f for f in review.flags if f not in media_flags(post)]
        if failures and post.revision == 0:
            fixes = failures + (review.judge.fixes if review.judge else [])
            en, ar = write_bilingual(self.judge.service, slot, brand, post.brief, post, fixes)
            post = Post.model_validate(
                {
                    **post.model_dump(),
                    "en": en,
                    "ar": ar,
                    "revision": 1,
                    "prompt_hashes": {
                        **post.prompt_hashes,
                        **prompt_hashes(
                            self.judge.service, ["copy_en_revision", "copy_ar_revision"]
                        ),
                    },
                }
            )
            review = self.check(post, slot, brand)
        return post, review
