"""FR-11, FR-12: first insights implementation is the offline simulator."""

from datetime import UTC, timedelta
from typing import Protocol

from instabay.core.learning import FidelityResult, MetricsSnapshot
from instabay.core.schemas import Post, Publication, Slot
from sim.world import AudienceWorld, SimArm


class InsightsSource(Protocol):
    """NFR-05: both simulated and future Graph insights return normalized snapshots."""

    def fetch(
        self, post: Post, slot: Slot, publication: Publication, fidelity: FidelityResult
    ) -> MetricsSnapshot:
        """FR-11: ingest metrics only for a stored authorized publication."""
        ...


class FidelitySource(Protocol):
    """FR-08: synthetic fixture labels today; calibrated D1 engines in Phase 6."""

    def check(self, post: Post, slot: Slot) -> FidelityResult:
        """FR-13: evidence is bound to the exact post, never inferred from judge averages."""
        ...


class SimulatedInsights:
    """FR-12: dry-run exports feed the previously frozen synthetic audience."""

    def __init__(self, world: AudienceWorld) -> None:
        self.world = world

    def fetch(
        self, post: Post, slot: Slot, publication: Publication, fidelity: FidelityResult
    ) -> MetricsSnapshot:
        """NFR-03: scheduled+48h logical observation time survives retry, unlike wall time."""
        if publication.post_id != post.id or publication.content_hash != post.content_hash:
            raise ValueError("Insights require the exact published content")
        arm = fidelity.executed_arm or slot.arm
        observation = self.world.observe(SimArm.model_validate(arm.model_dump()), slot.id)
        return MetricsSnapshot(
            post_id=post.id,
            content_hash=post.content_hash,
            source=f"simulated:{self.world.config.version}:seed={self.world.seed}",
            observed_at=(slot.scheduled_at + timedelta(hours=48)).astimezone(UTC),
            observed_arm=arm,
            arm_assumed=fidelity.executed_arm is None,
            reach=observation.reach,
            views=observation.views,
            likes=observation.likes,
            comments=observation.comments,
            saved=observation.saved,
            shares=observation.shares,
            watch_through=observation.watch_through,
        )
