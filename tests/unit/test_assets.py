"""FR-02, FR-04, FR-08: owner photo library, pillar labels, weekly mix and suggestions."""

import base64
import io
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from instabay.assets.classify import STATE, agreement, asset_questions, classify_assets
from instabay.assets.export import export_library
from instabay.assets.library import AssetLibrary
from instabay.assets.plan import OwnerCadence, load_cadence, save_cadence, suggest_assets
from instabay.core.planner import plan_week
from instabay.decisions.engine import DecisionUnavailableError
from instabay.decisions.jev_http import SystemOneConfig
from instabay.decisions.vision import (
    D3_FLASH,
    D3FlashHTTPEngine,
    FakeVisionEngine,
    VisionFixture,
    vision_key,
)
from tests.support import demo_brand

PILLARS = ["underwater", "spa", "guests", "local", "offers"]


def jpeg(
    color: tuple[int, int, int], size: tuple[int, int] = (64, 48), exif: bool = False
) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color)
    if exif:
        data = Image.Exif()
        data[0x0112] = 6  # rotate 90 degrees on display
        image.save(buffer, format="JPEG", exif=data.tobytes())
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def library(tmp_path: Path):
    with AssetLibrary(tmp_path / "ws", root=tmp_path) as lib:
        yield lib


def owner_photo(library: AssetLibrary, shade: int, pillar: str | None = None, note: bool = True):
    asset = library.add(
        jpeg(((shade * 37) % 256, (shade * 11) % 256, (shade * 73) % 256)),
        added_by="owner",
        rights_confirmed=True,
        note_en=f"Photo {shade}" if note else "",
        note_ar=f"صورة {shade}" if note else "",
    )
    return library.review(asset.id, owner_pillar=pillar) if pillar else asset


def test_upload_dedupes_requires_rights_and_rejects_non_images(library):
    first = owner_photo(library, 10)
    assert owner_photo(library, 10).id == first.id and len(library.all()) == 1
    assert library.path(first).exists() and first.file.startswith("ws/assets/originals/")
    with pytest.raises(ValueError, match="Confirm you own"):
        library.add(jpeg((1, 2, 3)), added_by="x", rights_confirmed=False)
    with pytest.raises(ValueError, match="JPEG, PNG or WebP"):
        library.add(b"not an image", added_by="x", rights_confirmed=True)


def test_exif_is_stripped_and_rotation_applied(library):
    asset = library.add(jpeg((9, 9, 9), (64, 48), exif=True), added_by="o", rights_confirmed=True)
    with Image.open(library.path(asset)) as stored:
        assert not stored.getexif() and stored.size == (48, 64)
    assert (asset.width, asset.height) == (48, 64)


def fixture_for(library, asset, pillar: str, confidence: float, people: float) -> VisionFixture:
    state_hash, questions_hash, shas = vision_key(
        STATE, asset_questions(demo_brand()), [library.path(asset)]
    )
    return VisionFixture(
        state_hash=state_hash,
        questions_hash=questions_hash,
        images_sha256=shas,
        response={
            "answers": {
                "pillar": {"choice": pillar, "confidence": confidence},
                "people": {"noul": people},
            }
        },
    )


def test_classifier_labels_low_confidence_needs_review_and_agreement(library):
    a, b, c = (owner_photo(library, s) for s in (10, 20, 30))
    engine = FakeVisionEngine(
        [
            fixture_for(library, a, "underwater", 0.91, 0.1),
            fixture_for(library, b, "spa", 0.42, 0.8),
        ]
    )
    report = classify_assets(library, engine, demo_brand())
    assert (report.classified, report.failed) == (2, [c.id])
    a, b = library.get(a.id), library.get(b.id)
    assert a.pillar == "underwater" and a.people == pytest.approx(0.1)
    assert b.model_pillar == "spa" and b.pillar is None and b.needs_review
    assert classify_assets(library, engine, demo_brand()).skipped == 2
    library.review(a.id, owner_pillar="underwater")
    library.review(b.id, owner_pillar="guests")
    score = agreement(library.all())
    assert (score.labelled, score.agree, score.accuracy) == (2, 1, 0.5)
    assert score.kappa == pytest.approx(1 / 3)


def test_d3_client_sends_images_and_requires_opt_in(library, monkeypatch):
    asset = owner_photo(library, 40)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "pillar": {
                        "type": "choice",
                        "choice": "local",
                        "confidence": 0.3,
                        "probabilities": {"local": 0.55, "spa": 0.45},
                    },
                    "people": {"noul": 0.2},
                }
            },
        )

    config = SystemOneConfig(base_url="http://127.0.0.1:18790", revision="r1", model=D3_FLASH)
    questions = asset_questions(demo_brand())
    engine = D3FlashHTTPEngine(
        config, confirm_external=True, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(DecisionUnavailableError, match="HUMAN"):
        engine.decide(STATE, questions, [library.path(asset)])
    monkeypatch.setenv("INSTABAY_DECISIONS_ENABLED", "1")
    answers = engine.decide(STATE, questions, [library.path(asset)])
    assert answers["pillar"].choice == "local"
    assert answers["pillar"].probabilities == {"local": 0.55, "spa": 0.45}
    assert base64.b64decode(seen["images"][0]) == library.path(asset).read_bytes()
    assert seen["model"] == D3_FLASH and seen["revision"] == "r1"
    with pytest.raises(ValueError, match="d3-flash"):
        D3FlashHTTPEngine(config.model_copy(update={"model": "other"}))
    library.add(jpeg((1, 1, 1)), added_by="o", rights_confirmed=True, note_en="x", note_ar="س")
    report = classify_assets(library, engine, demo_brand())
    assert report.classified == 2
    top = library.get(asset.id)
    assert top.model_confidence == 0.55 and top.pillar == "local"


def test_owner_cadence_pins_exact_weekly_mix(library):
    brand = demo_brand()
    mix = OwnerCadence(posts_per_week=7, reels_per_week=3, carousels_per_week=2)
    save_cadence(library, brand, mix)
    assert load_cadence(library, brand) == mix
    slots = plan_week(brand, "a" * 64, "run", date(2026, 10, 12), cadence=mix.cadence(brand))
    assert Counter(s.arm.format for s in slots) == {"reel": 3, "carousel": 2, "photo": 2}
    with pytest.raises(ValueError, match="cannot exceed"):
        OwnerCadence(posts_per_week=3, reels_per_week=2, carousels_per_week=2)


@settings(max_examples=60, deadline=None)
@given(
    posts=st.integers(1, 7),
    reels=st.integers(1, 7),
    carousels=st.integers(0, 6),
)
def test_planner_honors_any_feasible_owner_mix(posts, reels, carousels):
    brand = demo_brand()
    try:
        mix = OwnerCadence(posts_per_week=posts, reels_per_week=reels, carousels_per_week=carousels)
        rhythm = mix.cadence(brand)
    except ValueError:
        return
    slots = plan_week(brand, "a" * 64, "run", date(2026, 10, 12), cadence=rhythm)
    counts = Counter(s.arm.format for s in slots)
    assert len(slots) == posts
    assert counts["reel"] == reels and counts["carousel"] == carousels
    assert counts["photo"] == mix.photos_per_week
    for pillar in brand.pillars:
        share = sum(s.arm.pillar == pillar.id for s in slots)
        assert math.ceil(pillar.min_share * posts - 1e-9) <= share
        assert share <= math.floor(pillar.max_share * posts + 1e-9)


def test_suggestions_prefer_pillar_photos_never_repeat_singles_and_flag_shortfall(library):
    brand = demo_brand()
    for index, pillar in enumerate(PILLARS * 2):
        owner_photo(library, 10 + index, pillar)
    unapproved = library.add(
        jpeg((250, 1, 1)),
        added_by="model",
        rights_confirmed=True,
        origin="generated",
        parent_id=library.all()[0].id,
        recipe={"preset": "low_waterline"},
        note_en="Waterline view",
        note_ar="منظر من مستوى الماء",
    )
    library.review(unapproved.id, owner_pillar=PILLARS[0])
    mix = OwnerCadence(posts_per_week=7, reels_per_week=2, carousels_per_week=2)
    slots = plan_week(brand, "a" * 64, "run", date(2026, 10, 12), cadence=mix.cadence(brand))
    suggestions = suggest_assets(slots, library.all())
    by_id = {a.id: a for a in library.all()}
    singles = [i for s in suggestions.values() if s.format == "photo" for i in s.primary]
    assert len(singles) == len(set(singles))
    assert all(unapproved.id not in s.pool for s in suggestions.values())
    for slot in slots:
        s = suggestions[slot.id]
        assert by_id[s.primary[0]].pillar == slot.arm.pillar
        if s.format == "reel":
            assert len(s.primary) == 4 and s.shortfall
    library.review(unapproved.id, approved=True)
    assert suggest_assets(slots, library.all()) != suggestions


def test_export_feeds_existing_evidence_contract(library):
    brand = demo_brand()
    for index, pillar in enumerate(PILLARS):
        owner_photo(library, 60 + index, pillar)
    owner_photo(library, 99, "spa", note=False)
    evidence, catalog = export_library(library, brand, library.workspace / "export")
    assert len(catalog.objects) == 5 and not evidence.reference_only
    assert set(evidence.pillar_guidance) == set(PILLARS)
    assert all(not o.reference_only and o.source == "photo" for o in catalog.objects)
    assert evidence.objects(library.root) == catalog
    view = library.add(
        jpeg((3, 3, 3)),
        added_by="model",
        rights_confirmed=True,
        origin="generated",
        parent_id=catalog.objects[0].id,
        recipe={"preset": "aerial"},
    )
    library.review(view.id, owner_pillar="local", note_en="Aerial", note_ar="منظر", approved=True)
    evidence, catalog = export_library(library, brand, library.workspace / "export")
    generated = catalog.get(view.id)
    assert not evidence.reference_only and generated.source == "synthetic"
    assert generated.approval_scope == "owner_approved_view" and not generated.reference_only


def test_unsure_d3_labels_go_to_the_vlm_judge(library):
    from instabay.assets.judge import FakePillarJudge, Verdict
    from instabay.decisions.vision import image_digest

    sure, unsure = owner_photo(library, 11), owner_photo(library, 12)
    engine = FakeVisionEngine(
        [
            fixture_for(library, sure, "spa", 0.9, 0.0),
            fixture_for(library, unsure, "local", 0.3, 0.0),
        ]
    )
    judge = FakePillarJudge(
        {image_digest(library.path(unsure)): Verdict(choice="guests", reason="Guests on loungers")}
    )
    report = classify_assets(library, engine, demo_brand(), judge=judge)
    assert (report.classified, report.judged, judge.calls) == (2, 1, 1)
    assert library.get(sure.id).pillar_source == "d3"
    judged = library.get(unsure.id)
    assert (judged.pillar, judged.pillar_source, judged.vlm_reason) == (
        "guests",
        "vlm",
        "Guests on loungers",
    )
    library.review(unsure.id, owner_pillar="guests")
    assert agreement(library.all(), "vlm").accuracy == 1.0
    assert agreement(library.all()).accuracy == 0.0
