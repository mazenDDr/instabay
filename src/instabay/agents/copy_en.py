"""FR-04: native English copy from the common brief, not from the Arabic caption."""

from instabay.agents.common import agent_inputs
from instabay.core.schemas import BrandConstitution, Brief, Copy, Slot
from instabay.llm import LLMService


class EnglishWriter:
    """FR-04: initial and single-revision prompts live in versioned Markdown."""

    def __init__(self, service: LLMService) -> None:
        self.service = service

    def write(
        self,
        slot: Slot,
        brand: BrandConstitution,
        brief: Brief,
        previous: Copy | None = None,
        fixes: list[str] | None = None,
    ) -> Copy:
        """FR-04, FR-08: revise once using checks, without changing the planned arm."""
        inputs = agent_inputs(slot=slot, brand=brand, brief=brief)
        if previous is not None:
            inputs.update(agent_inputs(previous=previous, fixes=fixes or []))
        return self.service.generate(
            template_name="copy_en_revision" if previous else "copy_en",
            slot_id=slot.id,
            inputs=inputs,
            output_type=Copy,
        )
