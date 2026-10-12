"""NFR-07, FR-13: strict canned variants and content-bound synthetic fidelity labels."""

from datetime import date
from pathlib import Path

import pytest

from instabay.adapters.fake_llm import FakeLLM, FakeLLMMissingFixture, FixtureCatalog
from instabay.adapters.fixture_fidelity import FixtureFidelity
from instabay.adapters.llm import CompletionRequest
from instabay.core.hashtags import select_hashtags
from instabay.core.planner import plan_week
from instabay.core.schemas import Brief, Copy, Post
from tests.support import demo_brand


def test_catalog_is_strict_for_unknown_template_slot_and_arm() -> None:
    catalog = FixtureCatalog.model_validate_json(
        Path("tests/fixtures/llm/cycle-catalog.json").read_bytes()
    )
    for template, slot, arm in [
        ("unknown", "cycle-w01-mon-1", {}),
        ("copy_en", "unknown", {}),
        ("copy_en", "cycle-w01-mon-1", {"pillar": "invented", "hook_style": "question"}),
    ]:
        with pytest.raises(FakeLLMMissingFixture):
            catalog.response(template, slot, arm)
    fake = FakeLLM(Path("tests/fixtures/llm"))
    request = CompletionRequest(
        template_name="brief_writer",
        slot_id="cycle-w01-mon-1",
        model="fake",
        prompt="fixture test",
        prompt_hash="a" * 64,
        inputs={},
        output_schema={},
        temperature=0,
    )
    with pytest.raises(FakeLLMMissingFixture):
        fake.complete(request)
    assert fake.calls == 0


def test_fixture_label_is_invalidated_by_actual_content_edit() -> None:
    brand = demo_brand()
    slot = plan_week(brand, "a" * 64, "cycle-w01", date(2026, 10, 12))[0]
    catalog = FixtureCatalog.model_validate_json(
        Path("tests/fixtures/llm/cycle-catalog.json").read_bytes()
    )
    arm = slot.arm.model_dump(mode="json")
    post = Post(
        id=slot.id,
        slot_id=slot.id,
        brand_hash=slot.brand_hash,
        format=slot.arm.format,
        brief=Brief.model_validate(catalog.response("brief_writer", slot.id, arm).response),
        en=Copy.model_validate(catalog.response("copy_en", slot.id, arm).response),
        ar=Copy.model_validate(catalog.response("copy_ar", slot.id, arm).response),
        hashtags=select_hashtags(brand),
        prompt_hashes={"copy_en": "a" * 64},
    )
    source = FixtureFidelity(catalog)
    confirmed = source.check(post, slot)
    assert confirmed.status == "confirmed"
    assert confirmed.executed_arm == slot.arm
    edited = Post.model_validate(
        {**post.model_dump(), "en": {**post.en.model_dump(), "caption": "A different hook."}}
    )
    result = source.check(edited, slot)
    assert result.content_hash == edited.content_hash
    assert result.status == "unverified"
    assert result.executed_arm is None
