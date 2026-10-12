"""FR-04, FR-05: selected media must prove the story and bind ordered images to approval."""

import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from instabay.content.evidence import ContentEvidence, EvidenceBrief
from instabay.content.photos import PhotoRecipe, PhotoStudio
from instabay.core.planner import plan_week
from instabay.core.schemas import BrandConstitution, canonical_hash
from instabay.video.direction import ObjectCatalog
from instabay.video.files import RenderError
from instabay.video.keyframes import runtime_identity

ROOT = Path(__file__).parents[2]


def campaign():
    brand = BrandConstitution.model_validate(
        yaml.safe_load((ROOT / "config/reference-campaign-brand.yaml").read_text())
    )
    evidence = ContentEvidence.model_validate(
        yaml.safe_load((ROOT / "config/reethi-faru-evidence.yaml").read_text())
    )
    objects = evidence.objects(ROOT)
    slots = plan_week(brand, canonical_hash(brand), "reference-w42", date(2026, 10, 12))
    return brand, evidence, objects, slots


def selection(slot):
    path = ROOT / "tests/fixtures/llm" / f"visual_brief__{slot.id}.json"
    return EvidenceBrief.model_validate(json.loads(path.read_text())["response"])


@pytest.mark.parametrize(
    "defect", ["unknown", "borrowed_fact", "duplicate", "wrong_cover", "format", "property"]
)
def test_source_selection_does_not_invent_or_borrow_evidence(defect):
    _, proof, objects, slots = campaign()
    slot = slots[1]
    data = selection(slot).model_dump()
    if defect == "unknown":
        data["media_ids"][0] = "unseen-pool"
    elif defect == "borrowed_fact":
        data["fact_ids"] = ["unseen-fact"]
    elif defect == "duplicate":
        data["media_ids"][1] = data["media_ids"][0]
    elif defect == "wrong_cover":
        data["brief"]["photo_uri"] = "not-the-selected-image.jpg"
    elif defect == "format":
        data["brief"]["reel_concept"] = {
            "hook": "x",
            "shots": ["x"],
            "overlay_en": "",
            "overlay_ar": "",
            "audio": "x",
            "cta": "x",
            "cover": "x",
        }
    else:
        raw = objects.model_dump()
        raw["objects"][0]["property_name"] = "Different Resort"
        with pytest.raises(ValidationError, match="different resorts"):
            ObjectCatalog.model_validate(raw)
        return
    with pytest.raises(ValueError):
        EvidenceBrief.model_validate(data).validate_selection(slot, proof, objects)


def test_mixed_format_floors_survive_a_score_preferring_all_reels():
    from instabay.core.schemas import PlanningPreferences

    brand, _, _, _ = campaign()
    slots = plan_week(
        brand,
        canonical_hash(brand),
        "mixed",
        date(2026, 10, 12),
        PlanningPreferences(format={"reel": 10000}),
    )
    assert [s.arm.format for s in slots] == [
        "photo",
        "carousel",
        "reel",
        "photo",
        "carousel",
        "reel",
        "photo",
    ]
    data = brand.model_dump()
    data["cadence"]["min_photos"] = 5
    with pytest.raises(ValidationError):
        BrandConstitution.model_validate(data)


def test_actual_multi_photo_render_has_stored_recipe_and_verified_cache(tmp_path):
    import sqlite3

    from PIL import Image

    _, _, objects, slots = campaign()
    story = selection(slots[1])
    recipe = PhotoRecipe(
        format="carousel",
        sources=[objects.get(i) for i in story.media_ids],
        runtime=runtime_identity(),
        story=story,
    )
    studio = PhotoStudio(ROOT, tmp_path / "images", tmp_path / "jobs.sqlite")
    result = studio.render(recipe)
    assert len(result.files) == 3 and not result.generated and result.reference_only
    for file in result.files:
        with Image.open(file.file) as image:
            assert image.size == (1080, 1350) and image.mode == "RGB"
            # Full portrait source inside 4:5: thin matte preserves source edges/context.
            assert image.getpixel((0, 700)) == (232, 238, 238)
    with sqlite3.connect(tmp_path / "jobs.sqlite") as db:
        stored = db.execute("select recipe_json from photo_render_job").fetchone()[0]
        assert PhotoRecipe.model_validate_json(stored) == recipe
    assert studio.render(recipe) == result
    Path(result.files[0].file).write_bytes(b"changed")
    with pytest.raises(RenderError, match="Cached photograph"):
        studio.render(recipe)
    data = recipe.model_dump()
    data["sources"].reverse()
    with pytest.raises(ValidationError, match="order"):
        PhotoRecipe.model_validate(data)


def test_format_failure_is_retried_inside_llm_validation(tmp_path):
    from instabay.adapters.fake_llm import FakeLLM
    from instabay.agents.visual_brief import VisualBriefWriter
    from instabay.db import SQLiteCallStore
    from instabay.llm import LLMService

    class InvalidThenValid(FakeLLM):
        def __init__(self):
            super().__init__(ROOT / "tests/fixtures/llm")
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            output = super().complete(request)
            if len(self.requests) == 1:
                raw = json.loads(output.output_json)
                raw["brief"]["reel_concept"] = None
                return output.model_copy(update={"output_json": json.dumps(raw)})
            return output

    brand, proof, objects, slots = campaign()
    client = InvalidThenValid()
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        result = VisualBriefWriter(LLMService(client, store)).write(
            slots[2], brand, proof, objects, []
        )
        assert result.brief.reel_concept is not None
        assert [r.status for r in store.calls()] == ["invalid_output", "success"]
        assert client.requests[1].validation_feedback


def test_factual_body_and_alt_cannot_inherit_a_hallucinated_writer_detail():
    from instabay.content.evidence import EvidenceCopyContext, EvidenceCopyDraft, factual_copy

    _, proof, _, slots = campaign()
    chosen = selection(slots[1])
    context = EvidenceCopyContext(
        selection=chosen,
        property_name=proof.property_name,
        geography=proof.geography,
        source_date_note=proof.source_date_note,
        facts=[f for f in proof.facts if f.id in chosen.fact_ids],
    )
    raw = EvidenceCopyDraft(
        opening="Explore the shoreline.",
        detail="An invented infinity pool under an open roof.",
        action="Save the views.",
        alt_text="Invented room interior",
        fact_id=chosen.fact_ids[0],
    )
    en = factual_copy(raw, context, "en")
    ar = factual_copy(raw, context, "ar")
    assert "pool" not in en.caption and "roof" not in en.caption and "interior" not in en.alt_text
    assert "1. " in en.caption and "3. " in ar.caption
    for fact in context.facts:
        assert fact.caption_en in en.caption and fact.caption_ar in ar.caption


def test_caption_boundary_rejects_borrowed_facts():
    from instabay.content.evidence import EvidenceCopyContext, caption_schema

    _, evidence, _, slots = campaign()
    selected = selection(slots[0])
    context = EvidenceCopyContext(
        selection=selected,
        property_name=evidence.property_name,
        geography=evidence.geography,
        source_date_note=evidence.source_date_note,
        facts=[f for f in evidence.facts if f.scene_id in selected.media_ids],
    )
    schema = caption_schema(context)
    raw = dict(opening="Already used", action="Save this view", fact_id=context.facts[0].id)
    assert schema.model_validate(raw).fact_id == context.facts[0].id
    raw.update(opening="A different thought", fact_id="unseen-pool")
    with pytest.raises(ValidationError, match="unknown visual fact"):
        schema.model_validate(raw)
