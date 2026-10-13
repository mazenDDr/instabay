"""FR-04, NFR-04: observed photographs constrain the story before copy or motion is written."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, field_validator, model_validator

from instabay.core.schemas import Boundary, Brief, Copy, Identifier, ReelConcept, Slot
from instabay.video.direction import ObjectCatalog
from instabay.video.files import local_file


class VisualFact(Boundary):
    """FR-08: a checkable observation in one named source photograph, not an amenity promise."""

    id: Identifier
    scene_id: Identifier
    text: str = Field(min_length=1)
    caption_en: str = Field(min_length=1)
    caption_ar: str = Field(min_length=1)


class Observation(Boundary):
    """FR-04: what the multimodal brief writer saw in a selected photo without owner facts."""

    media_id: Identifier
    en: str = Field(min_length=1, max_length=240)
    ar: str = Field(min_length=1, max_length=240)


class ContentEvidence(Boundary):
    """NFR-04: one property, historical source scope and pillar-specific evidence instructions."""

    property_name: str
    geography: str
    source_date_note: str
    objects_file: str
    facts: list[VisualFact] = Field(default_factory=list)
    pillar_guidance: dict[str, str]
    reference_only: bool = True

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({f.id for f in self.facts}) != len(self.facts):
            raise ValueError("Fact IDs must be unique")
        return self

    def objects(self, root: Path) -> ObjectCatalog:
        """NFR-03: evidence property and scene references must agree with the media catalog."""
        path = (root / self.objects_file).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Evidence catalog must be under the project root")
        catalog = ObjectCatalog.model_validate(yaml.safe_load(path.read_text()))
        if catalog.resort != self.property_name:
            raise ValueError("Evidence and photographs belong to different properties")
        if self.reference_only != any(o.reference_only for o in catalog.objects):
            raise ValueError("Evidence scope cannot contradict its photographs")
        for fact in self.facts:
            item = catalog.get(fact.scene_id)
            local_file(root, item.photo)
        return catalog


class EvidenceBrief(Boundary):
    """FR-04: a shared brief plus visible proof, ordered images and a specific pillar purpose."""

    brief: Brief
    media_ids: list[Identifier] = Field(min_length=1, max_length=5)
    # Filled by code from the selected photos (validate_selection still requires a fact per
    # image); a model-sent [] failed the whole post before code could fill it (2026-10-13).
    fact_ids: list[Identifier] = Field(default_factory=list)
    pillar_intent: str = Field(min_length=1, max_length=500)
    sequence_reason: str = Field(min_length=1, max_length=500)
    cta_kind: Literal["save", "compare", "comment", "swipe"] = "save"
    observations: list[Observation] = Field(
        default_factory=list, max_length=5, exclude_if=lambda v: not v
    )

    def facts(self, evidence: "ContentEvidence") -> list[VisualFact]:
        """FR-04: owner facts for the selected photos, then the writer's own observations."""
        owned = [f for f in evidence.facts if f.scene_id in self.media_ids]
        covered = {f.scene_id for f in owned}
        seen = [
            VisualFact(
                id=f"{o.media_id}-seen",
                scene_id=o.media_id,
                text=o.en,
                caption_en=o.en,
                caption_ar=o.ar,
            )
            for o in self.observations
            if o.media_id in self.media_ids and o.media_id not in covered
        ]
        return owned + seen

    def validate_selection(
        self, slot: Slot, evidence: ContentEvidence, catalog: ObjectCatalog
    ) -> None:
        """FR-04, FR-06: single photos, genuine multi-photo stories and scene-led films differ."""
        if slot.arm.pillar not in evidence.pillar_guidance:
            raise ValueError("No source-backed direction is available for this pillar")
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("Repeated images do not make a carousel or a new scene")
        if slot.arm.format == "photo" and len(self.media_ids) != 1:
            raise ValueError("A single-photo post needs exactly one image")
        if slot.arm.format == "carousel" and len(self.media_ids) < 2:
            raise ValueError("A carousel must contain multiple different photographs")
        if slot.arm.format == "reel" and len(self.media_ids) < 3:
            raise ValueError("A scenic reel needs at least three complete scenes")
        if (slot.arm.format == "reel") != (self.brief.reel_concept is not None):
            raise ValueError("The concept must match the planned format")
        selected = [catalog.get(i) for i in self.media_ids]
        if len({o.photo.sha256 for o in selected}) != len(selected):
            raise ValueError("Renamed copies of one photograph are not media variety")
        if self.brief.photo_uri != selected[0].photo.uri:
            raise ValueError("The brief must use its first selected real photograph")
        facts = {f.id: f for f in [*evidence.facts, *self.facts(evidence)]}
        if len(set(self.fact_ids)) != len(self.fact_ids):
            raise ValueError("Evidence facts must be distinct")
        for fact_id in self.fact_ids:
            if fact_id not in facts or facts[fact_id].scene_id not in self.media_ids:
                raise ValueError("The brief cites an unknown or unselected visual fact")
        if any(
            not any(facts[i].scene_id == scene for i in self.fact_ids) for scene in self.media_ids
        ):
            raise ValueError("Each selected image needs a visible reason to be in the story")


class EvidenceCopyContext(Boundary):
    """FR-04: both writers see the same visual proof, never the other language's caption."""

    selection: EvidenceBrief
    property_name: str
    geography: str
    source_date_note: str
    facts: list[VisualFact]
    reference_only: bool = True


class StillBrief(Brief):
    """FR-04: a feed brief cannot masquerade as a reel concept."""

    reel_concept: None = None


class ReelBrief(Brief):
    """FR-06: a reel concept is required at the schema boundary, not merely in instructions."""

    reel_concept: ReelConcept


class PhotoEvidenceBrief(EvidenceBrief):
    """FR-05: advertise a one-image constraint in the provider's JSON schema."""

    brief: StillBrief
    media_ids: list[Identifier] = Field(min_length=1, max_length=1)


class CarouselEvidenceBrief(EvidenceBrief):
    """FR-05: a real album needs multiple selected photographs."""

    brief: StillBrief
    media_ids: list[Identifier] = Field(min_length=2, max_length=5)


class ReelEvidenceBrief(EvidenceBrief):
    """FR-06: a scene-led film needs a concept and at least three views."""

    brief: ReelBrief
    media_ids: list[Identifier] = Field(min_length=3, max_length=5)


class EvidenceCopyDraft(Boundary):
    """FR-04: enforce one concrete opening, a visible detail and a distinct action field."""

    opening: str = Field(min_length=1, max_length=120)
    detail: str = Field(default="", max_length=300)
    action: str = Field(min_length=1, max_length=100)
    alt_text: str = Field(default="", max_length=600)
    fact_id: Identifier

    @field_validator("detail", "alt_text", mode="before")
    @classmethod
    def compiled_by_code(cls, value: object) -> str:
        """FR-04: factual body and alt text come from the facts; model text here is dropped.

        Qwen3.5-9B filled `detail` with 400+ characters and failed the whole post twice.
        """
        return ""


def caption_schema(context: EvidenceCopyContext) -> type[EvidenceCopyDraft]:
    """FR-04: reject unsupported facts; style defects remain visible in pending review."""
    from collections.abc import Callable
    from typing import cast

    from pydantic import create_model, model_validator

    ids = [f.id for f in context.facts]

    def grounded(draft: EvidenceCopyDraft) -> EvidenceCopyDraft:
        if draft.fact_id not in ids:
            raise ValueError("Caption cites an unknown visual fact")
        return draft

    return cast(
        type[EvidenceCopyDraft],
        create_model(
            "GroundedCaptionDraft",
            __base__=EvidenceCopyDraft,
            fact_id=(str, Field(json_schema_extra={"enum": [str(v) for v in ids]})),
            __validators__={
                "grounded": cast(
                    Callable[..., EvidenceCopyDraft], model_validator(mode="after")(grounded)
                )
            },
        ),
    )


def factual_copy(
    draft: EvidenceCopyDraft, context: EvidenceCopyContext, language: Literal["en", "ar"]
) -> Copy:
    """FR-04, NFR-04: compile factual body/alt from source clauses, leaving framing to the LLM."""
    facts = {f.id: f for f in context.facts}
    if draft.fact_id not in facts:
        raise ValueError("Caption cites an unknown visual fact")

    def clause(fact: VisualFact) -> str:
        return fact.caption_en if language == "en" else fact.caption_ar

    if context.selection.brief.reel_concept is None and len(context.selection.media_ids) > 1:
        ordered = [
            next(facts[i] for i in context.selection.fact_ids if facts[i].scene_id == scene)
            for scene in context.selection.media_ids
        ]
        body = "\n".join(f"{index}. {clause(fact)}" for index, fact in enumerate(ordered, 1))
        alt = " ".join(clause(f) for f in ordered)
    else:
        body = clause(facts[draft.fact_id])
        alt = body
    return Copy(caption="\n\n".join([draft.opening, body, draft.action]), alt_text=alt)
