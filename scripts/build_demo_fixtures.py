"""NFR-07: explicitly author the fixed seven-slot offline demo; never a runtime fallback."""

import json
from pathlib import Path

from instabay.adapters.fake_llm import Fixture
from instabay.core.schemas import Brief, Copy, JudgeSample, ReelConcept, RubricScores

SLOTS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
COPY = [
    (
        "3 ways to slow down: a little light, a little shade, a little quiet.\n"
        "Save this for a gentler morning.",
        "ثلاث طرق للتمهّل: قليل من الضوء، وقليل من الظل، ولحظة هدوء.\nاحفظ هذه الفكرة لصباح أهدأ.",
    ),
    (
        "When did you last leave a little space for quiet?\n"
        "Palm shadows. No rush.\nSave a slower moment.",
        "متى كانت آخر مرة منحت فيها نفسك لحظة هدوء؟\n"
        "ظلال النخيل، ووقت بلا عجلة.\nاحفظ لحظة على مهل.",
    ),
    (
        "What would your unhurried morning look like?\n"
        "Terracotta arches and palm shadows.\nTell us your ideal pace.",
        "كيف تتخيّل صباحك على مهل؟\nأقواس دافئة وظلال نخيل.\nأخبرنا عن إيقاع صباحك المفضّل.",
    ),
    (
        "Which colors remind you of Hurghada?\nWarm walls, green palms, blue water.\n"
        "Save a little Red Sea inspiration.",
        "أيّ الألوان تذكّرك بالغردقة؟\nجدران دافئة، ونخيل أخضر، ومياه زرقاء.\n"
        "احفظ شيئاً من إلهام البحر الأحمر.",
    ),
    (
        "Where would you pause in this scene?\nA quiet arch. A patch of shade.\n"
        "Pick your favorite detail.",
        "أين تودّ التوقّف في هذا المشهد؟\nقوس هادئ، ومساحة من الظل.\nاختر تفصيلك المفضّل.",
    ),
    (
        "What is the first thing you plan for an escape?\n"
        "A slower morning is a lovely place to start.\nSave this for your travel wish list.",
        "ما أول ما تخطّط له في رحلتك القادمة؟\nصباح هادئ بداية جميلة.\n"
        "احفظ هذه الفكرة لقائمة رحلاتك.",
    ),
    (
        "What if your next escape began with a slower pace?\n"
        "Palms, warm colors, a moment to breathe.\nSave this reel concept for later.",
        "ماذا لو بدأت رحلتك القادمة بإيقاع أهدأ؟\n"
        "نخيل، وألوان دافئة، ولحظة لالتقاط الأنفاس.\nاحفظ فكرة هذا المقطع لوقت لاحق.",
    ),
]


def main() -> None:
    """NFR-07: regenerate schema-valid canned JSON, without networks or model calls."""
    directory = Path("tests/fixtures/llm")
    for index, day in enumerate(SLOTS):
        slot_id = f"2026-w42-{day}-1"
        concept = (
            ReelConcept(
                hook="Ask about a slower escape",
                shots=[
                    "Approved crop of the real-photo terrace: a modest push toward an arch",
                    "Approved palm detail: gentle movement only; do not invent a facility",
                    "Return to the real approved terrace still for the closing moment",
                ],
                overlay_en="A slower moment.",
                overlay_ar="لحظة على مهل.",
                audio="Human-approved instrumental library track; no track selected yet",
                cta="Save this concept",
                cover="assets/photos/grand_resort_day.jpg",
            )
            if day == "sun"
            else None
        )
        brief = Brief(
            angle="An unhurried moment in a real resort reference photograph",
            hook="Open with three details" if index == 0 else "Open with a question",
            key_message="Light, shade and time to breathe; no facility or offer claims",
            visual_description="A terracotta arcade framing palms and a courtyard",
            photo_uri="assets/photos/grand_resort_day.jpg",
            cta="Save or share a detail",
            must_not=["invented facilities", "prices", "identifiable faces"],
            reel_concept=concept,
        )
        en = Copy(
            caption=COPY[index][0],
            alt_text=(
                "Terracotta arches frame palms and a courtyard in a reference photo "
                "of The Grand Resort Hurghada."
            ),
        )
        ar = Copy(
            caption=COPY[index][1],
            alt_text="أقواس دافئة تحيط بنخيل وفناء في صورة مرجعية لمنتجع جراند ريزورت الغردقة.",
        )
        judge = JudgeSample(
            scores=RubricScores(
                voice=5, pillar_fit=5, caption_visual_match=4, hashtag_policy=5, format_cta=4
            ),
            fixes=[],
        )
        for name, response, tokens in [
            ("brief_writer", brief, 120),
            ("copy_en", en, 75),
            ("copy_ar", ar, 100),
            ("judge", judge, 65),
            ("copy_en_revision", en, 75),
            ("copy_ar_revision", ar, 100),
        ]:
            fixture = Fixture.model_validate(
                {
                    "template_name": name,
                    "slot_id": slot_id,
                    "response": response.model_dump(mode="json"),
                    "input_tokens": 180,
                    "output_tokens": tokens,
                }
            )
            (directory / f"{name}__{slot_id}.json").write_text(
                json.dumps(fixture.model_dump(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
