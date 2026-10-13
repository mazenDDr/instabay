"""FR-04: native Arabic copy; the writer never receives the English caption."""

from instabay.adapters.llm import ImageInput
from instabay.agents.common import agent_inputs
from instabay.content.evidence import EvidenceCopyContext, caption_schema, factual_copy
from instabay.content.feedback import OwnerFeedback
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
        visual_context: EvidenceCopyContext | None = None,
        previous_openings: list[str] | None = None,
        images: list[ImageInput] | None = None,
        feedback: OwnerFeedback | None = None,
    ) -> Copy:
        """FR-04, FR-08: compose or revise native AR from the shared brief and fixes."""
        inputs = agent_inputs(slot=slot, brand=brand, brief=brief)
        if visual_context:
            inputs = agent_inputs(
                slot=slot,
                brief=brief,
                visual_context=visual_context,
                previous_openings=previous_openings or [],
            )
            if feedback is not None and not feedback.empty:
                inputs["owner_feedback"] = feedback.for_language("ar")  # type: ignore[assignment]
            draft = self.service.generate(
                template_name="grounded_copy_ar",
                slot_id=slot.id,
                inputs=inputs,
                output_type=caption_schema(visual_context),
                images=images,
                max_output_tokens=800,
            )
            if draft.fact_id not in {f.id for f in visual_context.facts}:
                raise ValueError("Caption cites an unknown visual fact")
            return factual_copy(draft, visual_context, "ar")
        if previous is not None:
            inputs.update(agent_inputs(previous=previous, fixes=fixes or []))
        return self.service.generate(
            template_name="copy_ar_revision" if previous else "copy_ar",
            slot_id=slot.id,
            inputs=inputs,
            output_type=Copy,
        )
