"""NFR-07: explicitly synthetic confidence policies and answers for cascade control-flow tests."""

import json
from pathlib import Path

from instabay.core.schemas import BrandConstitution, Post, Slot, canonical_hash
from instabay.decisions.calibration import CalibrationProfile, Cell
from instabay.decisions.engine import LANGUAGES, FakeDecisionEngine
from instabay.decisions.questions import decision_state, questions_for


def engine_for(
    root: Path,
    posts: list[tuple[Post, Slot]],
    brand: BrandConstitution,
    *,
    bad: str | None = None,
    confidence: float = 0.98,
    d1_only: bool = False,
) -> FakeDecisionEngine:
    root.mkdir(parents=True, exist_ok=True)
    for post, slot in posts:
        for lang in LANGUAGES:
            questions = questions_for(brand, lang)
            if d1_only:
                questions = {k: v for k, v in questions.items() if k in ("hook", "pillar")}
            answers = {
                "hook": {"choice": slot.arm.hook_style, "confidence": confidence},
                "pillar": {"choice": slot.arm.pillar, "confidence": confidence},
                "hardsell": {"noul": 0.02, "confidence": confidence},
                "luxury": {"score": 0, "confidence": confidence},
                "register": {
                    "choice": "natural" if lang == "en" else "msa",
                    "confidence": confidence,
                },
            }
            if bad == "low_register" and lang == "ar":
                answers["register"]["confidence"] = 0.4
            if bad == "adverse":
                answers["hardsell"]["noul"] = 0.98
            if bad == "leaked":
                answers["hook"]["choice"] = (
                    "statement" if slot.arm.hook_style != "statement" else "question"
                )
            if bad == "disagree" and lang == "ar":
                answers["hook"]["choice"] = (
                    "statement" if slot.arm.hook_style != "statement" else "question"
                )
            fixture = {
                "state_hash": canonical_hash({"state": decision_state(post, brand, lang)}),
                "questions_hash": canonical_hash({k: v.wire() for k, v in questions.items()}),
                "response": {"answers": {k: v for k, v in answers.items() if k in questions}},
            }
            (root / f"{post.id}_{lang}.json").write_text(
                json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
            )
    return FakeDecisionEngine(root)


def profile_for(
    brand: BrandConstitution, engine_id: str = "fake-systemone-v1"
) -> CalibrationProfile:
    return CalibrationProfile(
        engine_id=engine_id,
        brand_hash=canonical_hash(brand),
        provenance="synthetic",
        dataset_hash="0" * 64,
        split_items={"train": [], "validation": [], "test": []},
        status="enabled",
        cells={
            f"{lang}.{qid}": Cell(
                question_hash=q.hash,
                temperature=1,
                threshold=0.8,
                validation_n=30,
                test_n=30,
                accepted_test_n=30,
                precision=1,
                precision_ci95=(0.886, 1),
                accuracy=1,
                ece_before=0.02,
                ece_after=0.02,
                escalation_rate=0,
                enabled=True,
            )
            for lang in LANGUAGES
            for qid, q in questions_for(brand, lang).items()
        },
    )
