"""FR-11, NFR-07: simulator replay, schema and frozen pre-optimizer evidence."""

import json
from pathlib import Path

import pytest

from sim.world import AudienceWorld, Observation, SimArm

ARM = SimArm(
    pillar="underwater", format="photo", time_bucket="evening_19_21", hook_style="question"
)


@pytest.mark.determinism
def test_frozen_observation() -> None:
    expected = json.loads(Path("tests/fixtures/sim/seed7.json").read_text())
    assert AudienceWorld(7).observe(ARM, "week1-post1").model_dump() == expected


def test_replay_is_independent_of_request_order() -> None:
    world = AudienceWorld(7)
    first = world.observe(ARM, "one")
    world.observe(ARM.model_copy(update={"format": "reel"}), "two")
    assert first == world.observe(ARM, "one") == AudienceWorld(7).observe(ARM, "one")
    assert first != AudienceWorld(8).observe(ARM, "one")


@pytest.mark.parametrize("format", ["photo", "carousel", "reel"])
def test_counts_and_watch_through(format: str) -> None:
    arm = SimArm.model_validate({**ARM.model_dump(), "format": format})
    for seed in range(20):
        observation = AudienceWorld(seed).observe(arm, "post")
        assert 0 <= observation.engagement_rate <= 1
        assert observation.views >= observation.reach >= 1
        assert (observation.watch_through is not None) == (format == "reel")
        # Computed rates are output-only, not an untrusted input reward.
        payload = observation.model_dump(exclude={"engagement_rate"})
        assert Observation.model_validate(payload) == observation


def test_unknown_arm_and_empty_event_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown simulator pillar"):
        AudienceWorld(7).observe(ARM.model_copy(update={"pillar": "invented"}), "post")
    with pytest.raises(ValueError, match="stable event"):
        AudienceWorld(7).observe(ARM, " ")
