"""FR-08: D3 untrusted text gate; uncertain text waits for human review before prompt insertion."""

from typing import Literal

from instabay.core.schemas import Boundary
from instabay.decisions.calibration import CalibrationProfile
from instabay.decisions.engine import DecisionEngine, Language, Question, normalize_answers
from instabay.decisions.questions import prompt


class GuardResult(Boundary):
    """FR-08: a classifier cannot authorize publishing or other tool calls."""

    decision: Literal["allow", "block", "review"]
    reason: str


class InjectionGuard:
    """FR-08: fail closed on unavailable or uncalibrated evidence, no prompt concatenation."""

    def __init__(
        self,
        engine: DecisionEngine,
        profile: CalibrationProfile | None,
        brand_hash: str,
        *,
        allow_synthetic: bool = False,
    ) -> None:
        self.engine, self.profile, self.brand_hash, self.allow_synthetic = (
            engine,
            profile,
            brand_hash,
            allow_synthetic,
        )

    def check(self, text: str, language: Language) -> GuardResult:
        question = Question(type="noul", instructions=prompt("injection", language))
        try:
            answers = self.engine.decide(text, {"injection": question})
            answer = normalize_answers(
                {"answers": {k: v.model_dump() for k, v in answers.items()}},
                {"injection": question},
            )["injection"]
            confidence = (
                self.profile.confidence(
                    answer,
                    "injection",
                    language,
                    question.hash,
                    engine_id=self.engine.engine_id,
                    brand_hash=self.brand_hash,
                    synthetic_engine=self.engine.synthetic,
                    allow_synthetic=self.allow_synthetic,
                )
                if self.profile
                else None
            )
            if confidence is None:
                return GuardResult(
                    decision="review",
                    reason="Untrusted text needs calibrated evidence or human review",
                )
            return GuardResult(
                decision="block" if answer.noul is not None and answer.noul >= 0.5 else "allow",
                reason="Calibrated D3; text still treated as untrusted data",
            )
        except (ValueError, RuntimeError, OSError):
            return GuardResult(decision="review", reason="Decision engine unavailable or invalid")
