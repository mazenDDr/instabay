"""FR-06: a director translates the shared brief into an evidence-grounded film."""

from collections.abc import Callable
from typing import Any, cast

from pydantic import Field, JsonValue, create_model, model_validator

from instabay.agents.visual_brief import scene_images
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


def unique_photos[Intent: CreativeIntent](intent: Intent, available: list[str]) -> Intent:
    """FR-06: a photo tour shows each photo once, with text only on its first and last shot.

    Qwen3.5-9B closed both real reels on the opening photo (a 'bookend'). The hook and CTA
    roles stay where they are; only the repeated photo is swapped or, if none is left, dropped.
    """
    if any(b.action != "photo_camera" for b in intent.beats):
        return intent
    spare = [i for i in available if i not in {b.object_id for b in intent.beats}]
    seen: set[str] = set()
    beats: list[BeatIntent] = []
    last = len(intent.beats) - 1
    for index, beat in enumerate(intent.beats):
        if beat.object_id in seen:
            if spare:
                beat = beat.model_copy(update={"object_id": spare.pop(0)})
            elif index == last and beats:
                # No unused photo: the previous shot carries the closing call to action.
                keep = ("role", "overlay", "brief_anchor", "text_position", "purpose")
                beats[-1] = beats[-1].model_copy(update={k: getattr(beat, k) for k in keep})
                continue
            else:
                continue
        seen.add(beat.object_id)
        beats.append(beat)
    if len(beats) > 2 and not any(b.role == "reveal" for b in beats):
        beats[-2] = beats[-2].model_copy(update={"role": "reveal"})
    # Text only on the opening and closing shots; the photos carry the middle of the tour.
    blank = {"overlay": beats[0].overlay.model_copy(update={"en": "", "ar": ""})}
    beats = [
        b if i in (0, len(beats) - 1) else b.model_copy(update=blank) for i, b in enumerate(beats)
    ]
    return intent.model_copy(update={"beats": beats})


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
        see_images: bool = False,
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
                    # Editorial diversity is mechanical, not a reason to invent more scenery.
                    beats = intent.beats[1:] + intent.beats[:1]
                    beats = [
                        b.model_copy(
                            update={
                                "role": "hook"
                                if i == 0
                                else "cta"
                                if i == len(beats) - 1
                                else "reveal",
                                "brief_anchor": "hook"
                                if i == 0
                                else "cta"
                                if i == len(beats) - 1
                                else "visual_description",
                            }
                        )
                        for i, b in enumerate(beats)
                    ]
                    intent = ScenicIntent.model_validate(
                        intent.model_copy(update={"beats": beats}).model_dump()
                    )
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
        else:
            available = [o.id for o in catalog.objects]

            def tour_checked(intent: CreativeIntent) -> CreativeIntent:
                # Run the editor's own rules inside validation so the model gets the exact
                # error and retries, instead of the reel failing after the call (2026-10-13).
                if intent.reel_id != reel_id:
                    raise ValueError("Director returned a different reel ID")
                VideoBoard(
                    brief=brief,
                    brief_hash=canonical_hash(brief),
                    plan=schedule_intent(unique_photos(intent, available)),
                    catalog=catalog,
                )
                return intent

            def blank_overlays(value: Any) -> Any:
                # Middle tour shots carry no text; accept {} where the model left them blank.
                if isinstance(value, dict) and isinstance(value.get("beats"), list):
                    value = dict(value)
                    value["beats"] = [
                        {**b, "overlay": {"en": "", "ar": "", **(b.get("overlay") or {})}}
                        if isinstance(b, dict)
                        else b
                        for b in value["beats"]
                    ]
                return value

            output_type = cast(
                type[CreativeIntent],
                create_model(
                    "BoundPhotoIntent",
                    __base__=CreativeIntent,
                    __validators__={
                        "blank_overlays": cast(
                            Callable[..., Any], model_validator(mode="before")(blank_overlays)
                        ),
                        "tour_checked": cast(
                            Callable[..., CreativeIntent],
                            model_validator(mode="after")(tour_checked),
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
            images=scene_images(catalog, [o.id for o in catalog.objects]) if see_images else None,
        )
        if intent.reel_id != reel_id:
            raise ValueError("Director returned a different reel ID")
        plan = schedule_intent(unique_photos(intent, [o.id for o in catalog.objects]))
        return VideoBoard(brief=brief, brief_hash=canonical_hash(brief), plan=plan, catalog=catalog)
