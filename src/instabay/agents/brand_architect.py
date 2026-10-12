"""FR-01: generate a draft constitution; human editing/freezing is never automatic."""

from instabay.agents.common import agent_inputs
from instabay.core.schemas import BrandConstitution, BrandInput
from instabay.llm import LLMService


class BrandArchitect:
    """FR-01: schema-valid draft only, with content provenance in the LLM ledger."""

    def __init__(self, service: LLMService) -> None:
        self.service = service

    def draft(self, brief: BrandInput) -> BrandConstitution:
        """FR-01: no code path here writes or freezes config/brand.yaml."""
        return self.service.generate(
            template_name="brand_architect",
            slot_id="brand-draft",
            inputs=agent_inputs(brief=brief),
            output_type=BrandConstitution,
        )
