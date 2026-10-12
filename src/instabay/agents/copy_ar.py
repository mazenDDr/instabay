"""FR-04: native Arabic copy; the writer never receives the English caption."""

from instabay.agents.common import agent_inputs
from instabay.core.schemas import BrandConstitution, Brief, Copy, Slot
from instabay.llm import LLMService


class ArabicWriter:
    """FR-04: Arabic prompt, examples and register are kept independent of EN copy."""

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
        """FR-04, FR-08: compose or revise native AR from the shared brief and fixes."""
        inputs = agent_inputs(slot=slot, brand=brand, brief=brief)
        if previous is not None:
            inputs.update(agent_inputs(previous=previous, fixes=fixes or []))
        return self.service.generate(
            template_name="copy_ar_revision" if previous else "copy_ar",
            slot_id=slot.id,
            inputs=inputs,
            output_type=Copy,
        )
