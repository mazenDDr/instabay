"""FR-04, FR-06: shared brief plus reel concept, without generating media."""

from instabay.agents.common import agent_inputs
from instabay.core.schemas import BrandConstitution, Brief, Slot
from instabay.llm import LLMService


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
