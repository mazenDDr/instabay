"""FR-08, FR-13: calibrated bilingual D1 evidence; no LLM can choose or update bandit arms."""

from typing import cast

from pydantic import JsonValue

from instabay.core.learning import FidelityResult
from instabay.core.schemas import Arm, BrandConstitution, Post, Slot
from instabay.decisions.calibration import CalibrationProfile
from instabay.decisions.engine import LANGUAGES, DecisionEngine, normalize_answers
from instabay.decisions.questions import decision_state, questions_for


class CalibratedFidelity:
    """FR-13: EN/AR consensus needed; unknown evidence never claims the planned arm executed."""

    def __init__(
        self,
        engine: DecisionEngine,
        profile: CalibrationProfile | None,
        brand: BrandConstitution,
        *,
        allow_synthetic: bool = False,
    ) -> None:
        self.engine, self.profile, self.brand, self.allow_synthetic = (
            engine,
            profile,
            brand,
            allow_synthetic,
        )

    def check(self, post: Post, slot: Slot) -> FidelityResult:
        """FR-13: semantic D1 only; time/format remain stored facts, live rewards stay separate."""
        observed = []
        try:
            for lang in LANGUAGES:
                questions = {
                    k: v
                    for k, v in questions_for(self.brand, lang).items()
                    if k in ("hook", "pillar")
                }
                raw = self.engine.decide(
                    cast(dict[str, JsonValue], decision_state(post, self.brand, lang)), questions
                )
                answers = normalize_answers(
                    {"answers": {k: v.model_dump() for k, v in raw.items()}}, questions
                )
                if self.profile is None or any(
                    self.profile.confidence(
                        answer,
                        qid,
                        lang,
                        questions[qid].hash,
                        engine_id=self.engine.engine_id,
                        brand_hash=post.brand_hash,
                        synthetic_engine=self.engine.synthetic,
                        allow_synthetic=self.allow_synthetic,
                    )
                    is None
                    for qid, answer in answers.items()
                ):
                    raise ValueError("No trusted calibrated bilingual D1 evidence")
                observed.append((answers["hook"].choice, answers["pillar"].choice))
            if observed[0] != observed[1]:
                raise ValueError("EN/AR executed-arm disagreement")
            executed = Arm.model_validate(
                {
                    **slot.arm.model_dump(),
                    "hook_style": observed[0][0],
                    "pillar": observed[0][1],
                    "format": post.format,
                }
            )
        except (ValueError, RuntimeError, OSError):
            executed = None
        return FidelityResult(
            post_id=post.id,
            content_hash=post.content_hash,
            planned_arm=slot.arm,
            executed_arm=executed,
            status="unverified"
            if executed is None
            else "confirmed"
            if executed == slot.arm
            else "leaked",
            source=self.engine.engine_id,
            reason="Bilingual calibrated semantic D1; no live reward/time inference"
            if executed
            else "Missing, uncalibrated or conflicting D1 evidence",
        )
