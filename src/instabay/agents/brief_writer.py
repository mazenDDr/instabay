"""FR-04, FR-06: shared brief plus reel concept, without generating media."""

from instabay.agents.common import agent_inputs
from instabay.core.schemas import BrandConstitution, Brief, Slot
from instabay.llm import LLMService
from instabay.video.shotlist import Keyframe, ShotList


class BriefWriter:
    """FR-04: both languages receive the same structured semantic brief."""

    def __init__(self, service: LLMService) -> None:
        self.service = service

    def write(self, slot: Slot, brand: BrandConstitution) -> Brief:
        """FR-06: require a concept for a reel slot; recipes arrive in Phase 7."""
        brief = self.service.generate(
            template_name="brief_writer",
            slot_id=slot.id,
            inputs=agent_inputs(slot=slot, brand=brand),
            output_type=Brief,
        )
        if (slot.arm.format == "reel") != (brief.reel_concept is not None):
            raise ValueError("Reel concepts must match the planned slot format")
        return brief

    def shot_list(
        self, slot: Slot, brand: BrandConstitution, brief: Brief, approved_stills: list[Keyframe]
    ) -> ShotList:
        """FR-06: write native overlays against approved stills; never invent approval."""
        if slot.arm.format != "reel" or not approved_stills:
            raise ValueError("Shot lists require a reel slot and approved still inputs")
        shots = self.service.generate(
            template_name="shot_list",
            slot_id=slot.id,
            inputs=agent_inputs(
                slot=slot,
                brand=brand,
                brief=brief,
                approved_stills=[s.model_dump_json() for s in approved_stills],
            ),
            output_type=ShotList,
            max_output_tokens=2400,
        )
        if shots.reel_id != slot.id or any(
            shot.keyframe not in approved_stills for shot in shots.shots
        ):
            raise ValueError("Shot writer invented or changed a still approval")
        return shots
