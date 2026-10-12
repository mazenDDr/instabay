"""FR-14, NFR-07: explicitly author benchmark corpus and canned evaluator/translation examples."""

import json
from datetime import date, timedelta
from pathlib import Path

from instabay.adapters.fake_llm import Fixture, FixtureCatalog
from instabay.benchmarks.corpus import Corpus, CorpusCase, NegativeControl
from instabay.benchmarks.humans import TranslationCase
from instabay.benchmarks.models import ArabicScores
from instabay.core.planner import plan_week
from instabay.core.schemas import BrandConstitution, Copy, JudgeSample, RubricScores, canonical_hash


def main() -> None:
    """FR-14: no model calls and no policy/simulator results determine these fixtures."""
    root = Path("bench")
    fixtures = root / "fixtures/llm"
    fixtures.mkdir(parents=True, exist_ok=True)
    catalog = FixtureCatalog.model_validate_json(
        Path("tests/fixtures/llm/cycle-catalog.json").read_bytes()
    )
    brand = BrandConstitution.model_validate(
        json.loads(Path("tests/fixtures/llm/brand_architect__brand-draft.json").read_text())[
            "response"
        ]
    )
    digest = canonical_hash(brand)
    cases, translations = [], []
    native = json.loads((root / "fixtures/authored_native.json").read_text())
    if len(native) != 21 or len({row["ar"] for row in native}) != 21:
        raise ValueError("Author exactly 21 unique native benchmark cases")
    for week in range(1, 4):
        slots = plan_week(
            brand, digest, f"cycle-w{week:02d}", date(2026, 10, 12) + timedelta(weeks=week - 1)
        )
        for slot in slots:
            arm = slot.arm.model_dump(mode="json")
            index = len(cases)
            brief = catalog.response("brief_writer", slot.id, arm).response
            en = Copy(
                caption=native[index]["en"],
                alt_text="Terracotta arches and palms in a Grand Resort Hurghada reference photo.",
            )
            ar = Copy(
                caption=native[index]["ar"],
                alt_text="أقواس دافئة ونخيل في صورة مرجعية لمنتجع جراند ريزورت الغردقة.",
            )
            signature = canonical_hash(
                {
                    "brief": brief,
                    "en": en.model_dump(mode="json"),
                    "ar": ar.model_dump(mode="json"),
                    "format": slot.arm.format,
                }
            )
            cases.append(CorpusCase(slot=slot, content_signature=signature))
            for template, copy, tokens in (("copy_en", en, 75), ("copy_ar", ar, 100)):
                recorded = Fixture(
                    template_name=template,
                    slot_id=slot.id,
                    response=copy.model_dump(mode="json"),
                    input_tokens=180,
                    output_tokens=tokens,
                )
                (fixtures / f"{template}__{slot.id}.json").write_text(
                    json.dumps(recorded.model_dump(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            response = ArabicScores(fluency=5, naturalness=4, brand_voice=5)
            fixture = Fixture(
                template_name="arabic_judge",
                slot_id=slot.id,
                response=response.model_dump(mode="json"),
                input_tokens=180,
                output_tokens=70,
            )
            (fixtures / f"arabic_judge__{slot.id}.json").write_text(
                json.dumps(fixture.model_dump(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if len(translations) < 20:
                translations.append(
                    TranslationCase(
                        post_id=slot.id,
                        caption=native[index]["mt"],
                    )
                )
    corpus = Corpus(version="fixed-fixture-21-v2", brand_hash=digest, cases=cases)
    (root / "corpus.json").write_text(corpus.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (root / "fixtures/translations.json").write_text(
        json.dumps([case.model_dump() for case in translations], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    for index in range(1, 11):
        response = JudgeSample(
            scores=RubricScores(
                voice=2, pillar_fit=1, caption_visual_match=2, hashtag_policy=5, format_cta=1
            ),
            fixes=["Generic hotel copy has no specific pillar angle or relaxed brand voice"],
        )
        fixture = Fixture(
            template_name="judge",
            slot_id=f"negative-{index:02d}",
            response=response.model_dump(mode="json"),
            input_tokens=180,
            output_tokens=65,
        )
        (fixtures / f"judge__negative-{index:02d}.json").write_text(
            json.dumps(fixture.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    generic = [
        (
            "Enjoy your stay. Book your next trip with us.",
            "استمتع بإقامتك. احجز رحلتك القادمة معنا.",
        ),
        ("Make new memories on your next holiday.", "اصنع ذكريات جديدة في إجازتك القادمة."),
        (
            "Your next trip is waiting. Start planning today.",
            "رحلتك القادمة تنتظرك. ابدأ التخطيط اليوم.",
        ),
        ("Take a break and enjoy a little time away.", "خذ استراحة واستمتع بوقت بعيد عن الروتين."),
        ("Every trip can be a new beginning.", "يمكن لكل رحلة أن تكون بداية جديدة."),
        (
            "A holiday is always a nice idea. Save this post.",
            "الإجازة فكرة جميلة دائماً. احفظ هذا المنشور.",
        ),
        ("Where will your next journey take you?", "إلى أين ستأخذك رحلتك القادمة؟"),
        ("Travel your way and make the most of every day.", "سافر بطريقتك واستمتع بكل يوم."),
        ("Good times begin with a holiday plan.", "تبدأ الأوقات الجميلة بالتخطيط لإجازة."),
        (
            "Discover your next escape. Add it to your wish list.",
            "اكتشف رحلتك القادمة وأضفها إلى قائمة أمنياتك.",
        ),
    ]
    controls = [
        NegativeControl(
            id=f"negative-{index:02d}",
            en=Copy(caption=en, alt_text="A hotel photograph."),
            ar=Copy(caption=ar, alt_text="صورة فندق."),
        )
        for index, (en, ar) in enumerate(generic, 1)
    ]
    (root / "fixtures/negative_controls.json").write_text(
        json.dumps(
            [control.model_dump(mode="json") for control in controls], ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
