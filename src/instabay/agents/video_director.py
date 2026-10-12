"""FR-06: a director translates the shared brief into an evidence-grounded film."""

from collections.abc import Callable
from typing import Any, cast

from pydantic import Field, JsonValue, create_model, model_validator

from instabay.core.schemas import Brief, canonical_hash
from instabay.llm import LLMService
from instabay.video.direction import (
    BeatIntent,
    CreativeIntent,
    ObjectCatalog,
    ScenicIntent,
    VideoBoard,
    schedule_intent,
)


class VideoDirector:
    """FR-06: objects and editorial decisions are creative outputs; approvals are not."""

    def __init__(self, service: LLMService) -> None:
        self.service = service

    def direct(
        self,
        reel_id: str,
        brief: Brief,
        catalog: ObjectCatalog,
        previous_scene_orders: list[list[str]] | None = None,
    ) -> VideoBoard:
        """FR-06: preserve the brief, reject unknown objects and surface missing real media."""
        output_type: type[CreativeIntent] = CreativeIntent
        if catalog.edit_style == "scenic":
            count = min(5, len(catalog.objects))

            def text_policy(value: Any) -> Any:
                # The scenic editor owns legibility; raw model text remains in the call audit.
                if isinstance(value, dict) and isinstance(value.get("beats"), list):
                    value = dict(value)
                    beats = [
                        {**beat, "overlay": {"en": "", "ar": ""}}
                        if isinstance(beat, dict)
                        else beat
                        for beat in value["beats"]
                    ]
                    if beats and all(isinstance(beat, dict) for beat in beats):
                        beats[0]["role"] = "hook"
                        beats[-1]["role"] = "cta"
                    value["beats"] = beats
                return value

            def grounded(intent: ScenicIntent) -> ScenicIntent:
                if intent.reel_id != reel_id:
                    raise ValueError("Director returned a different reel ID")
                if len({b.object_id for b in intent.beats}) != len(intent.beats):
                    raise ValueError("Each scenic scene needs a distinct source object")
                if [b.object_id for b in intent.beats] in (previous_scene_orders or []):
                    raise ValueError("Choose a different scene order for this pillar's film")
                VideoBoard(
                    brief=brief,
                    brief_hash=canonical_hash(brief),
                    plan=schedule_intent(intent),
                    catalog=catalog,
                )
                return intent

            output_type = cast(
                type[CreativeIntent],
                create_model(
                    "BoundScenicIntent",
                    __base__=ScenicIntent,
                    beats=(list[BeatIntent], Field(min_length=count, max_length=count)),
                    __validators__={
                        "text_policy": cast(
                            Callable[..., Any], model_validator(mode="before")(text_policy)
                        ),
                        "grounded": cast(
                            Callable[..., ScenicIntent], model_validator(mode="after")(grounded)
                        ),
                    },
                ),
            )
        intent = self.service.generate(
            template_name="video_director",
            slot_id=reel_id,
            output_type=output_type,
            inputs={
                "reel_id": reel_id,
                "edit_style": catalog.edit_style,
                "available_unique_scenes": len(catalog.objects),
                "previous_scene_orders": cast(list[JsonValue], previous_scene_orders or []),
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
