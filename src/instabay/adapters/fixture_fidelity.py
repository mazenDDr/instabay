"""FR-08, FR-13: synthetic D1 labels for the exact canned content, never a real engine."""

from typing import cast

from pydantic import JsonValue

from instabay.adapters.fake_llm import FakeLLMMissingFixture, FixtureCatalog
from instabay.core.learning import FidelityResult
from instabay.core.schemas import Arm, Boundary, Hash, Post, Slot, canonical_hash


class FidelityLabel(Boundary):
    """FR-08: canned arm label plus a signature of the known brief and native copies."""

    executed_arm: Arm
    content_signature: Hash


def content_signature(post: Post) -> str:
    """FR-13: human edits invalidate canned semantic evidence, including alt text."""
    return canonical_hash(
        {
            "brief": post.brief.model_dump(mode="json"),
            "en": post.en.model_dump(mode="json"),
            "ar": post.ar.model_dump(mode="json"),
            "format": post.format,
        }
    )


class FixtureFidelity:
    """NFR-07: replay labeled synthetic D1 cases, not uncalibrated judge scores."""

    def __init__(self, catalog: FixtureCatalog) -> None:
        self.catalog = catalog

    def check(self, post: Post, slot: Slot) -> FidelityResult:
        """FR-13: mismatches stay unverified; do not guess an edited caption's arm."""
        label = None
        try:
            fixture = self.catalog.response(
                "fidelity", slot.id, cast(dict[str, JsonValue], slot.arm.model_dump(mode="json"))
            )
            label = FidelityLabel.model_validate(fixture.response)
        except FakeLLMMissingFixture:
            pass
        matches = label is not None and label.content_signature == content_signature(post)
        executed = label.executed_arm if matches and label else None
        return FidelityResult(
            post_id=post.id,
            content_hash=post.content_hash,
            planned_arm=slot.arm,
            executed_arm=executed,
            status=("confirmed" if executed == slot.arm else "leaked") if matches else "unverified",
            source="synthetic-fixture-d1-v1",
            reason=(
                "Exact labeled canned brief/copy replay; not a calibrated engine"
                if matches
                else "No exact labeled fixture content; semantic D1 is deferred to Phase 6"
            ),
        )
