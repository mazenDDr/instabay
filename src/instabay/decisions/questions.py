"""FR-08: atomic D1/D2 questions with Markdown instructions and language-specific policies."""

from pathlib import Path

from instabay.core.schemas import BrandConstitution, Post, Slot
from instabay.decisions.engine import Answer, Language, Question

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def prompt(name: str, language: Language) -> str:
    """NFR-03: full instructions participate in each question hash."""
    return (PROMPTS / f"decision_{name}_{language}.md").read_text().strip()


def questions_for(brand: BrandConstitution, language: Language) -> dict[str, Question]:
    """FR-08: D1 observes actual hook/pillar; D2 checks tone, sales pressure and register."""
    return {
        "hook": Question(
            type="choice",
            instructions=prompt("hook", language),
            criteria={
                "question": "opens with a question",
                "statement": "opens with a statement",
                "number": "opens with a number/list",
            },
        ),
        "pillar": Question(
            type="choice",
            instructions=prompt("pillar", language),
            criteria={p.id: p.description for p in brand.pillars},
        ),
        "hardsell": Question(type="noul", instructions=prompt("hardsell", language)),
        "luxury": Question(
            type="score",
            instructions=prompt("luxury", language),
            criteria=["restrained and quiet", "warm and welcoming", "pushy or exaggerated"],
        ),
        "register": Question(
            type="choice",
            instructions=prompt("register", language),
            criteria=(
                {"natural": "natural English", "awkward": "awkward or translated English"}
                if language == "en"
                else {
                    "msa": "Modern Standard Arabic",
                    "egyptian": "Egyptian dialect",
                    "gulf": "Gulf dialect",
                }
            ),
        ),
    }


def decision_state(post: Post, brand: BrandConstitution, language: Language) -> dict[str, str]:
    """FR-08: do not reveal the planned arm to the classifier; keep trusted policy separate."""
    return {
        "caption": getattr(post, language).caption,
        "voice": str(getattr(brand.voice, language).model_dump()),
    }


def acceptable(
    answer: Answer, question_id: str, slot: Slot, brand: BrandConstitution, language: Language
) -> bool:
    """FR-08: a confident adverse classification never becomes a pass by itself."""
    if question_id == "hook":
        return answer.choice == slot.arm.hook_style
    if question_id == "pillar":
        return answer.choice == slot.arm.pillar
    if question_id == "hardsell":
        return answer.noul is not None and answer.noul < 0.5
    if question_id == "luxury":
        return answer.score is not None and answer.score <= 1
    if question_id == "register":
        expected = (
            "natural"
            if language == "en"
            else (
                "egyptian"
                if "egypt" in brand.voice.ar.register_.lower()
                else "gulf"
                if "gulf" in brand.voice.ar.register_.lower()
                else "msa"
            )
        )
        return answer.choice == expected
    return False
