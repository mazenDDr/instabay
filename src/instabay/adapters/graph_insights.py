"""FR-11: real long-format insights preserve missing data; no synthetic reward assumptions."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from instabay.adapters.graph_http import graph_request
from instabay.adapters.graph_models import GraphConfig, GraphID, GraphProtocolError
from instabay.adapters.graph_store import GraphStore
from instabay.adapters.graph_transport import GraphTransport
from instabay.core.schemas import Boundary, Hash, Identifier, UTCDateTime, canonical_hash
from instabay.core.tables import GraphObservationRow, MetricRow
from instabay.repository import Repository

MetricName = Literal[
    "views", "reach", "likes", "comments", "saved", "shares", "ig_reels_avg_watch_time"
]
BASE_METRICS = ("views", "reach", "likes", "comments", "saved", "shares")


class GraphMetric(Boundary):
    """FR-11: finite nonnegative provider values; average watch time stays in milliseconds."""

    name: MetricName
    value: float = Field(ge=0)

    @model_validator(mode="after")
    def integer_counts(self) -> Self:
        if self.name != "ig_reels_avg_watch_time" and not self.value.is_integer():
            raise ValueError("Graph counts must be integers")
        return self


class GraphInsightBatch(Boundary):
    """FR-11: missing/zero-reach observations never imply zero engagement or watch-through."""

    post_id: Identifier
    content_hash: Hash
    media_id: GraphID
    account_id: GraphID
    api_version: str
    observed_at: UTCDateTime
    metrics: list[GraphMetric]
    missing: list[str]

    @property
    def engagement_rate(self) -> float | None:
        values: dict[str, float] = {m.name: m.value for m in self.metrics}
        required = {"reach", "likes", "comments", "saved", "shares"}
        if not required <= values.keys() or values["reach"] == 0:
            return None
        # Real interaction types overlap: this raw ratio can exceed 1. Phase 6 owns learning.
        return sum(values[name] for name in required - {"reach"}) / values["reach"]


def parse_metrics(body: dict[str, object], requested: list[str]) -> list[GraphMetric]:
    """FR-11: lifetime totals only; absent values stay absent, malformed payloads are errors."""
    data = body.get("data")
    if not isinstance(data, list):
        raise GraphProtocolError("Insights data is not a list")
    metrics: list[GraphMetric] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict) or item.get("name") not in requested:
            raise GraphProtocolError("Unsupported insight metric")
        name = str(item["name"])
        if item.get("period", "lifetime") != "lifetime":
            raise GraphProtocolError("Only lifetime insight observations are supported")
        if name in seen:
            raise GraphProtocolError("Duplicate insight metric")
        seen.add(name)
        total, values = item.get("total_value"), item.get("values")
        value: object = None
        if isinstance(total, dict):
            value = total.get("value")
        elif isinstance(values, list) and len(values) == 1 and isinstance(values[0], dict):
            value = values[0].get("value")
        elif values == []:
            continue
        elif values is not None:
            raise GraphProtocolError("Unsupported insight value series")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GraphProtocolError("Insights metric is not numeric")
        try:
            metrics.append(GraphMetric.model_validate({"name": name, "value": value}))
        except ValueError:
            raise GraphProtocolError("Insights metric has an invalid value") from None
    return metrics


class GraphInsightSource(Protocol):
    """NFR-05: live ingestion is distinct from the simulator's exclusive bounded counts."""

    def fetch(self, post_id: str) -> GraphInsightBatch: ...


class GraphInsights:
    """FR-11: query parent published media only; ingestion never updates bandit posteriors."""

    def __init__(
        self,
        repository: Repository,
        config: GraphConfig,
        transport: GraphTransport,
        *,
        account_id: str,
        confirm_live: bool,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = GraphStore(repository, confirm_live=confirm_live)
        self.config, self.transport, self.account_id, self.now = config, transport, account_id, now

    def fetch(self, post_id: str) -> GraphInsightBatch:
        """FR-11: empty sets are valid pending observations, malformed payloads are errors."""
        with self.store.locked(post_id) as (session, post, _approval):
            receipt = self.store.receipt(session, post, self.config, self.account_id)
            if receipt is None or receipt.media_id is None:
                raise ValueError("Insights require a stored live publication with a media ID")
            metadata = graph_request(
                self.transport,
                "GET",
                f"/{receipt.media_id}",
                {"fields": "media_type,media_product_type"},
            )
            expected = {"photo": "IMAGE", "carousel": "CAROUSEL_ALBUM", "reel": "VIDEO"}[
                post.format
            ]
            if metadata.get("media_type") != expected or (
                post.format == "reel" and metadata.get("media_product_type") != "REELS"
            ):
                raise GraphProtocolError("Published media type does not match the approved post")
            requested = [*BASE_METRICS]
            if post.format == "reel":
                requested.append("ig_reels_avg_watch_time")
            body = graph_request(
                self.transport,
                "GET",
                f"/{receipt.media_id}/insights",
                {"metric": ",".join(requested)},
            )
            metrics = parse_metrics(body, requested)
            received = {m.name for m in metrics}
            metrics.sort(key=lambda metric: requested.index(metric.name))
            batch = GraphInsightBatch(
                post_id=post.id,
                content_hash=post.content_hash,
                media_id=receipt.media_id,
                account_id=self.account_id,
                api_version=self.config.api_version,
                observed_at=self.now(),
                metrics=metrics,
                missing=[name for name in requested if name not in received],
            )
            source = (
                f"graph:{self.config.login}:{self.config.api_version}:"
                f"account={self.account_id}:media={receipt.media_id}"
            )
            timestamp = batch.observed_at.isoformat()
            observation_id = canonical_hash({"post": post.id, "time": timestamp, "source": source})
            observation = session.get(GraphObservationRow, observation_id)
            if observation is not None and observation.observation_json != batch.model_dump_json():
                raise ValueError("Conflicting insight batch at the same timestamp")
            if observation is None:
                session.add(
                    GraphObservationRow(
                        id=observation_id, post_id=post.id, observation_json=batch.model_dump_json()
                    )
                )
            for metric in metrics:
                row = session.get(MetricRow, (post.id, metric.name, timestamp))
                if row is not None and (row.value != metric.value or row.source != source):
                    raise ValueError("Conflicting insight observation at the same timestamp")
                if row is None:
                    session.add(
                        MetricRow(
                            post_id=post.id,
                            name=metric.name,
                            observed_at=timestamp,
                            value=metric.value,
                            source=source,
                        )
                    )
            # Empty/partial observation provenance survives without invented metric rows.
            return batch
