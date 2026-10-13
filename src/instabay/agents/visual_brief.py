"""FR-04: choose a format-specific story from actual scene evidence before writing captions."""

from collections.abc import Callable
from typing import cast

from pydantic import Field, create_model, model_validator

from instabay.adapters.llm import ImageInput
from instabay.agents.common import agent_inputs
from instabay.content.evidence import (
    CarouselEvidenceBrief,
    ContentEvidence,
    EvidenceBrief,
    PhotoEvidenceBrief,
    ReelEvidenceBrief,
)
from instabay.core.schemas import BrandConstitution, Slot
from instabay.llm import LLMService
from instabay.video.direction import ObjectCatalog


def scene_images(catalog: ObjectCatalog, ids: list[str]) -> list[ImageInput]:
    """FR-04: the exact source photos a multimodal writer sees, in the given order."""
    return [
        ImageInput(id=i, uri=catalog.get(i).photo.uri, sha256=catalog.get(i).photo.sha256)
        for i in ids
    ]


class VisualBriefWriter:
    """FR-04, NFR-04: source facts and a pillar objective precede creative generation."""

    def __init__(self, service: LLMService) -> None:
        self.service = service

    def write(
        self,
        slot: Slot,
        brand: BrandConstitution,
        evidence: ContentEvidence,
        catalog: ObjectCatalog,
        previous_angles: list[str],
        used_photo_scenes: list[str] | None = None,
        pool: list[str] | None = None,
        see_images: bool = False,
    ) -> EvidenceBrief:
        """FR-04: distinct weekly angles, an ordered carousel and no unsupported facility claims.

        ``pool`` is the code-ranked asset suggestion for this slot; the writer orders and tells
        the story but may only choose among those images.
        """
        inputs = agent_inputs(slot=slot, evidence=evidence, previous_angles=previous_angles)
        candidates = [o for o in catalog.objects if not pool or o.id in pool]
        available = [
            o
            for o in candidates
            if slot.arm.format != "photo" or o.id not in (used_photo_scenes or [])
        ] or candidates
        allowed = [o.id for o in available]
        described = {f.scene_id for f in evidence.facts}
        inputs["scenes"] = [
            {
                "id": o.id,
                "photo_uri": o.photo.uri,
                "observed": o.observed,
                "has_facts": o.id in described,
            }
            for o in available
        ]
        inputs["post_format"] = slot.arm.format
        inputs["pillar_goal"] = evidence.pillar_guidance[slot.arm.pillar]

        def grounded(result: EvidenceBrief) -> EvidenceBrief:
            if (
                slot.arm.format == "reel"
                and catalog.edit_style != "scenic"
                and len(result.media_ids) < min(4, len(allowed))
            ):
                raise ValueError("A photo reel needs at least four different photos")
            if any(i not in allowed for i in result.media_ids):
                raise ValueError("Choose an available scene; single photos must vary before reuse")
            # Facts and the lead photo path are source metadata, not a bookkeeping task for the
            # model: Qwen3-8B chose valid carousel photos but copied another photo's path.
            result = result.model_copy(
                update={
                    "fact_ids": [f.id for f in result.facts(evidence)],
                    "brief": result.brief.model_copy(
                        update={"photo_uri": catalog.get(result.media_ids[0]).photo.uri}
                    ),
                }
            )
            result.validate_selection(slot, evidence, catalog)
            return result

        parent = cast(
            type[EvidenceBrief],
            {
                "photo": PhotoEvidenceBrief,
                "carousel": CarouselEvidenceBrief,
                "reel": ReelEvidenceBrief,
            }[slot.arm.format],
        )
        output_type = cast(
            type[EvidenceBrief],
            create_model(
                "GroundedEvidenceBrief",
                __base__=parent,
                media_ids=(
                    list[str],
                    Field(
                        min_length=1
                        if slot.arm.format == "photo"
                        else 2
                        if slot.arm.format == "carousel"
                        else 3,
                        max_length=1 if slot.arm.format == "photo" else 5,
                        json_schema_extra={
                            "items": {"type": "string", "enum": [str(v) for v in allowed]}
                        },
                    ),
                ),
                __validators__={
                    "grounded": cast(
                        Callable[..., EvidenceBrief], model_validator(mode="after")(grounded)
                    )
                },
            ),
        )
        result = self.service.generate(
            template_name="visual_brief",
            slot_id=slot.id,
            inputs=inputs,
            output_type=output_type,
            max_output_tokens=1200,
            images=scene_images(catalog, allowed) if see_images else None,
        )
        result.validate_selection(slot, evidence, catalog)
        return EvidenceBrief.model_validate(result.model_dump(mode="json"))
