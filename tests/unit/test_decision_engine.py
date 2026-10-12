"""FR-08: fake/typed contract checks precede native implementations."""

import json
from pathlib import Path

import pytest

from instabay.core.schemas import canonical_hash
from instabay.decisions.engine import (
    DecisionProtocolError,
    DecisionUnavailableError,
    FakeDecisionEngine,
    Question,
    normalize_answers,
)


def test_fake_exact_inputs_and_missing_fixture(tmp_path: Path) -> None:
    questions = {
        "hook": Question(
            type="choice", instructions="fixture hook", criteria={"question": "?", "statement": "."}
        )
    }
    fixture = {
        "state_hash": canonical_hash({"state": "fixture"}),
        "questions_hash": canonical_hash({k: v.wire() for k, v in questions.items()}),
        "response": {"answers": {"hook": {"choice": "question", "confidence": 0.94}}},
    }
    (tmp_path / "one.json").write_text(json.dumps(fixture))
    engine = FakeDecisionEngine(tmp_path)
    assert engine.decide("fixture", questions)["hook"].choice == "question"
    with pytest.raises(DecisionUnavailableError):
        engine.decide("unknown", questions)


def test_noul_jev_without_confidence_and_laya_explicit_confidence() -> None:
    questions = {"sell": Question(type="noul", instructions="fixture")}
    assert (
        normalize_answers({"answers": {"sell": {"noul": 0.03}}}, questions)["sell"].confidence
        == 0.97
    )
    assert (
        normalize_answers({"answers": {"sell": {"noul": 0.03, "confidence": 0.92}}}, questions)[
            "sell"
        ].confidence
        == 0.92
    )


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {"extra": {"noul": 0.1}},
        {"sell": {"noul": 2}},
        {"sell": {"noul": 0.1, "choice": "bad", "confidence": 0.9}},
    ],
)
def test_bad_answers_fail_closed(answers: object) -> None:
    with pytest.raises(DecisionProtocolError):
        normalize_answers(
            {"answers": answers}, {"sell": Question(type="noul", instructions="fixture")}
        )
