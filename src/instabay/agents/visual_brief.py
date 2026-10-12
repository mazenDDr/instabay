"""FR-04: choose a format-specific story from actual scene evidence before writing captions."""

from collections.abc import Callable
from typing import cast

from pydantic import Field, create_model, model_validator

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
    ) -> EvidenceBrief:
        """FR-04: distinct weekly angles, an ordered carousel and no unsupported facility claims."""
        inputs = agent_inputs(slot=slot, evidence=evidence, previous_angles=previous_angles)
        available = [
            o
            for o in catalog.objects
            if slot.arm.format != "photo" or o.id not in (used_photo_scenes or [])
        ] or catalog.objects
        allowed = [o.id for o in available]
        inputs["scenes"] = [
            {"id": o.id, "photo_uri": o.photo.uri, "observed": o.observed} for o in available
        ]
        inputs["post_format"] = slot.arm.format
        inputs["pillar_goal"] = evidence.pillar_guidance[slot.arm.pillar]

        def grounded(result: EvidenceBrief) -> EvidenceBrief:
            if any(i not in allowed for i in result.media_ids):
                raise ValueError("Choose an available scene; single photos must vary before reuse")
            # Facts are source metadata, not a bookkeeping task for the model.
            result = result.model_copy(
                update={
                    "fact_ids": [f.id for f in evidence.facts if f.scene_id in result.media_ids]
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
        )
        result.validate_selection(slot, evidence, catalog)
        return EvidenceBrief.model_validate(result.model_dump(mode="json"))
