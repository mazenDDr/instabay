"""FR-06: a director translates the shared brief into an evidence-grounded film."""

from instabay.core.schemas import Brief, canonical_hash
from instabay.llm import LLMService
from instabay.video.direction import CreativeIntent, ObjectCatalog, VideoBoard, schedule_intent


class VideoDirector:
    """FR-06: objects and editorial decisions are creative outputs; approvals are not."""

    def __init__(self, service: LLMService) -> None:
        self.service = service

    def direct(self, reel_id: str, brief: Brief, catalog: ObjectCatalog) -> VideoBoard:
        """FR-06: preserve the brief, reject unknown objects and surface missing real media."""
        intent = self.service.generate(
            template_name="video_director",
            slot_id=reel_id,
            output_type=CreativeIntent,
            inputs={
                "reel_id": reel_id,
                "brief": brief.model_dump(mode="json"),
                "observed_objects": [
                    {
                        "id": o.id,
                        "label": o.label,
                        "observed": o.observed,
                        "motion_available": o.clip is not None,
                        "allowed_actions": [a for a in o.allowed_actions],
                    }
                    for o in catalog.objects
                ],
            },
            max_output_tokens=3000,
        )
        if intent.reel_id != reel_id:
            raise ValueError("Director returned a different reel ID")
        plan = schedule_intent(intent)
        return VideoBoard(brief=brief, brief_hash=canonical_hash(brief), plan=plan, catalog=catalog)
