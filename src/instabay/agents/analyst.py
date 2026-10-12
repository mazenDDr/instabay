"""FR-11, FR-13: code ingests evidence and reports measurements; LLMs never update beliefs."""

from instabay.adapters.insights import FidelitySource, InsightsSource
from instabay.core.learning import WeekAnalysis
from instabay.repository import Repository


class Analyst:
    """FR-13: resumable learning from actual dry-run receipts, not unapproved drafts."""

    def __init__(
        self,
        repository: Repository,
        insights: InsightsSource,
        fidelity: FidelitySource,
        scope_id: str,
    ) -> None:
        self.repository = repository
        self.insights = insights
        self.fidelity = fidelity
        self.scope_id = scope_id

    def analyze(self, run_id: str) -> WeekAnalysis:
        """FR-11: rejected posts have no receipt, no simulated engagement and no learning."""
        slots = {slot.id: slot for slot in self.repository.slots(run_id)}
        records = []
        for publication in self.repository.publications(run_id):
            post = self.repository.post(publication.post_id)
            record = self.repository.learning_record(post.id)
            if record is None:
                slot = slots[post.slot_id]
                evidence = self.fidelity.check(post, slot)
                metrics = self.insights.fetch(post, slot, publication, evidence)
                record = self.repository.record_metrics(self.scope_id, metrics, evidence)
            elif record.scope_id != self.scope_id:
                raise ValueError("Observation belongs to a different audience/brand scope")
            records.append(record)
        reach = sum(record.metrics.reach for record in records)
        engagements = sum(
            record.metrics.likes
            + record.metrics.comments
            + record.metrics.saved
            + record.metrics.shares
            for record in records
        )
        return WeekAnalysis(
            run_id=run_id,
            exported=len(records),
            learned=sum(record.learned for record in records),
            leaked=sum(record.fidelity.status == "leaked" for record in records),
            unverified=sum(record.fidelity.status == "unverified" for record in records),
            reach=reach,
            engagements=engagements,
            engagement_rate=engagements / reach if reach else None,
        )
