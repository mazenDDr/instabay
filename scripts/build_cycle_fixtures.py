"""NFR-07: explicitly author a compact labeled cycle pack, without models or networks."""

import argparse
import json
from itertools import product
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from instabay.adapters.fake_llm import FixtureCatalog, FixtureGroup
from instabay.core.schemas import (
    Arm,
    Brief,
    Copy,
    JudgeSample,
    ReelConcept,
    RubricScores,
    canonical_hash,
)

TOPICS = {
    "underwater": ("Red Sea dreams below the surface.", "أحلام تحت سطح البحر الأحمر."),
    "spa": ("A wellness wish list begins with calm.", "تبدأ قائمة أمنيات العافية بلحظة هدوء."),
    "guests": ("Your next travel memory starts with an idea.", "تبدأ ذكريات سفرك القادمة بفكرة."),
    "local": (
        "Let Hurghada inspire your next travel wish list.",
        "دع الغردقة تلهم قائمة رحلاتك القادمة.",
    ),
    "offers": (
        "Booking inspiration: put a slower escape on your wish list.",
        "فكرة للحجز: أضف رحلة على مهل إلى قائمة أمنياتك.",
    ),
}
HOOKS = {
    "question": ("What would your next escape feel like?", "كيف تتخيّل رحلتك القادمة؟"),
    "statement": ("Leave a little room for quiet.", "اترك مساحة صغيرة للهدوء."),
    "number": (
        "3 details to savor: light, shade, quiet.",
        "ثلاثة تفاصيل تستحق التمهّل: ضوء، وظل، وهدوء.",
    ),
}
FACTORS = ["pillar", "format", "time_bucket", "hook_style"]


def copies(pillar: str, hook: str) -> tuple[Copy, Copy]:
    """FR-04: fixed native EN/AR examples, not machine translation or runtime generation."""
    return (
        Copy(
            caption=f"{HOOKS[hook][0]}\n{TOPICS[pillar][0]}\nSave this travel inspiration.",
            alt_text="Terracotta arches and palms in a Grand Resort Hurghada reference photo.",
        ),
        Copy(
            caption=f"{HOOKS[hook][1]}\n{TOPICS[pillar][1]}\nاحفظ هذه الفكرة لرحلتك القادمة.",
            alt_text="أقواس دافئة ونخيل في صورة مرجعية لمنتجع جراند ريزورت الغردقة.",
        ),
    )


def build(cycle_id: str, weeks: int) -> FixtureCatalog:
    """NFR-07: enumerate cases independently of any optimizer or simulator result."""
    brief_cases: dict[str, dict[str, JsonValue]] = {}
    labels: dict[str, dict[str, JsonValue]] = {}
    en_cases: dict[str, dict[str, JsonValue]] = {}
    ar_cases: dict[str, dict[str, JsonValue]] = {}
    for pillar, format, bucket, hook in product(
        TOPICS,
        ("photo", "carousel", "reel"),
        ("morning_08_10", "noon_12_14", "evening_19_21", "late_21_23"),
        HOOKS,
    ):
        arm = Arm.model_validate(
            {"pillar": pillar, "format": format, "time_bucket": bucket, "hook_style": hook}
        )
        en, ar = copies(pillar, hook)
        concept = (
            ReelConcept(
                hook=HOOKS[hook][0],
                shots=[
                    "Human-approved crop of the real reference arches; gentle push only",
                    "Return to the same photograph; do not invent any facility",
                ],
                overlay_en="Travel inspiration",
                overlay_ar="إلهام للسفر",
                audio="Human-approved library track; no track selected",
                cta="Save the concept",
                cover="assets/photos/grand_resort_day.jpg",
            )
            if format == "reel"
            else None
        )
        brief = Brief(
            angle=f"{pillar} travel inspiration, with no facility or offer claim",
            hook=HOOKS[hook][0],
            key_message=TOPICS[pillar][0],
            visual_description="Terracotta arches framing palms in a real reference photograph",
            photo_uri="assets/photos/grand_resort_day.jpg",
            cta="Save this travel inspiration",
            must_not=["invented facilities", "prices", "identifiable faces"],
            reel_concept=concept,
        )
        key = "|".join(str(arm.model_dump()[factor]) for factor in FACTORS)
        brief_cases[key] = cast(dict[str, JsonValue], brief.model_dump(mode="json"))
        labels[key] = {
            "executed_arm": cast(dict[str, JsonValue], arm.model_dump(mode="json")),
            "content_signature": canonical_hash(
                {
                    "brief": brief.model_dump(mode="json"),
                    "en": en.model_dump(mode="json"),
                    "ar": ar.model_dump(mode="json"),
                    "format": format,
                }
            ),
        }
        en_cases[f"{pillar}|{hook}"] = cast(dict[str, JsonValue], en.model_dump(mode="json"))
        ar_cases[f"{pillar}|{hook}"] = cast(dict[str, JsonValue], ar.model_dump(mode="json"))
    judge = JudgeSample(
        scores=RubricScores(
            voice=5, pillar_fit=5, caption_visual_match=4, hashtag_policy=5, format_cta=4
        ),
        fixes=[],
    )
    groups = {
        "brief_writer": FixtureGroup(
            selectors=FACTORS, cases=brief_cases, input_tokens=180, output_tokens=120
        ),
        "copy_en": FixtureGroup(
            selectors=["pillar", "hook_style"], cases=en_cases, input_tokens=180, output_tokens=75
        ),
        "copy_ar": FixtureGroup(
            selectors=["pillar", "hook_style"], cases=ar_cases, input_tokens=180, output_tokens=100
        ),
        "judge": FixtureGroup(
            selectors=[],
            cases={"": cast(dict[str, JsonValue], judge.model_dump(mode="json"))},
            input_tokens=180,
            output_tokens=65,
        ),
        "fidelity": FixtureGroup(selectors=FACTORS, cases=labels, input_tokens=0, output_tokens=0),
    }
    templates = {
        **{name: name for name in groups},
        "copy_en_revision": "copy_en",
        "copy_ar_revision": "copy_ar",
    }
    entries = {
        f"{template}__{cycle_id}-w{week:02d}-{day}-1": group
        for week in range(1, weeks + 1)
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        for template, group in templates.items()
    }
    return FixtureCatalog(entries=entries, groups=groups)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle-id", default="cycle")
    parser.add_argument("--weeks", type=int, default=12)
    parser.add_argument(
        "--output", type=Path, default=Path("tests/fixtures/llm/cycle-catalog.json")
    )
    args = parser.parse_args()
    if args.weeks < 1:
        parser.error("weeks must be positive")
    args.output.write_text(
        json.dumps(build(args.cycle_id, args.weeks).model_dump(), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
