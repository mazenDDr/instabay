"""FR-02, FR-03: constrained code planner using supplied factor scores."""

import math
from datetime import date, datetime, time, timedelta
from itertools import product
from typing import Literal

from instabay.core.schemas import (
    CAIRO,
    Arm,
    BrandConstitution,
    HookStyle,
    PlanningPreferences,
    PostFormat,
    Slot,
    TimeBucket,
)


def plan_week(
    brand: BrandConstitution,
    brand_hash: str,
    run_id: str,
    week_start: date,
    preferences: PlanningPreferences | None = None,
) -> list[Slot]:
    """FR-02: maximize supplied scores within integer shares, reel and quiet-hour limits."""
    if week_start.weekday() != 0:
        raise ValueError("Weekly plans must start on Monday")
    scores = preferences or PlanningPreferences()
    count = brand.cadence.posts_per_week
    ranges = [
        range(math.ceil(p.min_share * count - 1e-9), math.floor(p.max_share * count + 1e-9) + 1)
        for p in brand.pillars
    ]
    candidates = (mix for mix in product(*ranges) if sum(mix) == count)
    best = max(
        candidates,
        key=lambda mix: sum(
            n * scores.pillar.get(p.id, 0) for p, n in zip(brand.pillars, mix, strict=True)
        ),
    )
    pillars = [p.id for p, n in zip(brand.pillars, best, strict=True) for _ in range(n)]
    formats: list[PostFormat] = ["photo", "carousel", "reel"]
    hooks: list[HookStyle] = ["question", "statement", "number"]
    buckets: list[TimeBucket] = list(brand.cadence.windows_cairo)
    preferred_format = max(formats, key=lambda item: scores.format.get(item, 0))
    chosen_formats = [preferred_format] * count
    floors = {
        "photo": brand.cadence.min_photos,
        "carousel": brand.cadence.min_carousels,
        "reel": brand.cadence.min_reels,
    }
    required: list[PostFormat] = [
        format
        for round_number in range(max(floors.values()))
        for format in formats
        if floors[format] > round_number
    ]
    # Spread mandatory formats across the week rather than stacking identical formats at its end.
    if brand.cadence.min_photos or brand.cadence.min_carousels:
        for index, format in enumerate(required):
            chosen_formats[index * count // len(required)] = format
    else:
        chosen_formats[count - len(required) :] = required
    preferred_hook = max(hooks, key=lambda item: scores.hook_style.get(item, 0))
    preferred_bucket = max(buckets, key=lambda item: scores.time_bucket.get(item, 0))
    segments: tuple[Literal["egyptian", "gcc", "european"], ...] = ("egyptian", "gcc", "european")
    slots = []
    for index, pillar in enumerate(pillars):
        day = week_start + timedelta(days=index)
        exploration_bucket = buckets[-1] if buckets[-1] != preferred_bucket else buckets[0]
        exploration_hook = hooks[-1] if hooks[-1] != preferred_hook else hooks[0]
        bucket = exploration_bucket if index == 0 else preferred_bucket
        hook = exploration_hook if index == 0 else preferred_hook
        clock = time.fromisoformat(brand.cadence.windows_cairo[bucket])
        slots.append(
            Slot(
                id=f"{run_id}-{day.strftime('%a').lower()}-1",
                run_id=run_id,
                brand_hash=brand_hash,
                scheduled_at=datetime.combine(day, clock, tzinfo=CAIRO),
                arm=Arm(
                    pillar=pillar, format=chosen_formats[index], time_bucket=bucket, hook_style=hook
                ),
                segment=segments[index % len(segments)],
                explore=index == 0,
            )
        )
    return slots
