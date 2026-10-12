"""FR-08: typed decisions behind one protocol; confidence is never an approval."""

from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import Field, JsonValue, model_validator

from instabay.core.schemas import Boundary, Hash, canonical_hash

Language = Literal["en", "ar"]


class Question(Boundary):
    """FR-08: bounded primitives; instructions are loaded from versioned Markdown prompts."""

    type: Literal["choice", "score", "noul"]
    instructions: str = Field(min_length=1)
    criteria: dict[str, str] | list[str] | None = None

    @model_validator(mode="after")
    def valid_criteria(self) -> Self:
        if self.type == "choice" and (
            not isinstance(self.criteria, dict) or len(self.criteria) < 2
        ):
            raise ValueError("Choice needs at least two named options")
        if self.type == "score" and (not isinstance(self.criteria, list) or len(self.criteria) < 2):
            raise ValueError("Score needs at least two ordered levels")
        if self.type == "noul" and self.criteria is not None:
            raise ValueError("This adapter's Noul questions have no criteria")
        return self

    @property
    def hash(self) -> str:
        return canonical_hash(self)

    def wire(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class Answer(Boundary):
    """FR-08: exactly one primitive value and uncalibrated provider confidence."""

    choice: str | None = None
    score: float | None = None
    noul: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    abstained: bool = False

    @model_validator(mode="after")
    def one_value(self) -> Self:
        if sum(v is not None for v in (self.choice, self.score, self.noul)) != 1:
            raise ValueError("Answer requires exactly one typed value")
        return self

    @property
    def label(self) -> str | float | bool:
        if self.choice is not None:
            return self.choice
        if self.score is not None:
            return self.score
        assert self.noul is not None
        return self.noul >= 0.5


def normalize_answers(payload: object, questions: dict[str, Question]) -> dict[str, Answer]:
    """FR-08: normalize Jev/Laya; missing/extra IDs and invalid choices fail closed."""
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise DecisionProtocolError("Decision response lacks an answers map")
    raw = payload["answers"]
    if set(raw) != set(questions):
        raise DecisionProtocolError("Response question IDs do not match the request")
    result = {}
    for name, question in questions.items():
        value = raw[name]
        if not isinstance(value, dict):
            raise DecisionProtocolError("Decision answer is not an object")
        selected = {
            key: value[key]
            for key in ("choice", "score", "noul", "confidence", "abstained")
            if key in value
        }
        if question.type == "noul" and "confidence" not in selected:
            probability = value.get("noul")
            if isinstance(probability, bool) or not isinstance(probability, (float, int)):
                raise DecisionProtocolError("Noul probability is missing")
            selected["confidence"] = max(probability, 1 - probability)
        try:
            answer = Answer.model_validate(selected)
        except ValueError:
            raise DecisionProtocolError("Invalid typed answer") from None
        if question.type == "choice" and (
            not isinstance(question.criteria, dict) or answer.choice not in question.criteria
        ):
            raise DecisionProtocolError("Answer choice is not a requested option")
        if question.type == "score" and (
            answer.score is None
            or not isinstance(question.criteria, list)
            or not 0 <= answer.score <= len(question.criteria) - 1
        ):
            raise DecisionProtocolError("Score is outside the requested ordinal levels")
        if question.type == "noul" and answer.noul is None:
            raise DecisionProtocolError("Noul answer has the wrong type")
        result[name] = answer
    return result


class DecisionEngine(Protocol):
    """NFR-05: local/HTTP/fake implementations use the same typed application boundary."""

    engine_id: str
    synthetic: bool

    def decide(
        self, state: str | dict[str, JsonValue], questions: dict[str, Question]
    ) -> dict[str, Answer]: ...


class DecisionProtocolError(ValueError):
    """FR-08: sanitized contract failure; cascade escalates instead of trusting it."""


class DecisionUnavailableError(RuntimeError):
    """FR-08: unavailable dependency/endpoint; no model download is attempted by default."""


class DecisionFixture(Boundary):
    """NFR-07: explicitly synthetic, exact state/question hashes, no network."""

    state_hash: Hash
    questions_hash: Hash
    response: dict[str, JsonValue]


class FakeDecisionEngine:
    """NFR-07: fixture-first engine; unknown inputs fail rather than guessing semantic labels."""

    engine_id = "fake-systemone-v1"
    synthetic = True

    def __init__(self, fixtures: Path) -> None:
        self.fixtures = [
            DecisionFixture.model_validate_json(p.read_bytes())
            for p in sorted(fixtures.glob("*.json"))
        ]
        self.calls = 0

    def decide(
        self, state: str | dict[str, JsonValue], questions: dict[str, Question]
    ) -> dict[str, Answer]:
        self.calls += 1
        state_hash = canonical_hash({"state": state})
        questions_hash = canonical_hash({k: v.wire() for k, v in questions.items()})
        for fixture in self.fixtures:
            if (fixture.state_hash, fixture.questions_hash) == (state_hash, questions_hash):
                return normalize_answers(fixture.response, questions)
        raise DecisionUnavailableError("No exact synthetic decision fixture")
