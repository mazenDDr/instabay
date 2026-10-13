"""FR-11: read-only snapshot of the owner's own Instagram account; nothing is posted or learned.

The account's earlier posts were not made from bandit arms, so their numbers are shown to the
owner and summarized with plain statistics, but never written into posteriors (NFR-05).
"""

import json
import random
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, JsonValue

from instabay.adapters.graph_http import graph_request
from instabay.adapters.graph_insights import BASE_METRICS, GraphMetric, parse_metrics
from instabay.adapters.graph_models import (
    GraphAPIError,
    GraphConfig,
    GraphID,
    GraphProtocolError,
    GraphRateLimitError,
)
from instabay.adapters.graph_transport import GraphTransport
from instabay.core.schemas import Boundary, UTCDateTime

CAIRO = ZoneInfo("Africa/Cairo")
ACCOUNT_DB = Path("outputs/instagram/account.sqlite")
ACCOUNT_FIELDS = "user_id,username,account_type,followers_count,media_count"
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"
)
Format = Literal["photo", "carousel", "reel", "other"]


class AccountMedia(Boundary):
    """FR-11: one existing post with its lifetime insights, or the safe reason they are absent."""

    id: GraphID
    format: Format
    posted_at: UTCDateTime
    permalink: str = ""
    caption: str = Field(default="", max_length=200)
    like_count: int | None = None
    comments_count: int | None = None
    metrics: list[GraphMetric] = Field(default_factory=list)
    insights_error: str | None = None

    @property
    def engagement_rate(self) -> float | None:
        values: dict[str, float] = {m.name: m.value for m in self.metrics}
        parts = ("likes", "comments", "saved", "shares")
        if not values.get("reach") or any(p not in values for p in parts):
            return None
        return sum(values[p] for p in parts) / values["reach"]


class AccountSnapshot(Boundary):
    """FR-11: one read of the account; stored append-only so changes over time stay visible."""

    account_id: GraphID
    username: str
    account_type: str = ""
    followers: int | None = None
    media_count: int | None = None
    api_version: str
    observed_at: UTCDateTime
    media: list[AccountMedia]


def _format(item: dict[str, object]) -> Format:
    kind, product = item.get("media_type"), item.get("media_product_type")
    if kind == "VIDEO" or product == "REELS":
        return "reel"
    return {"IMAGE": "photo", "CAROUSEL_ALBUM": "carousel"}.get(str(kind), "other")  # type: ignore[return-value]


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def fetch_account(
    transport: GraphTransport,
    config: GraphConfig,
    account_id: str,
    *,
    limit: int = 25,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AccountSnapshot:
    """FR-11: GET requests only. A post whose insights are refused is kept with the error code."""
    profile = graph_request(transport, "GET", f"/{account_id}", {"fields": ACCOUNT_FIELDS})
    listing = graph_request(
        transport, "GET", f"/{account_id}/media", {"fields": MEDIA_FIELDS, "limit": str(limit)}
    )
    data = listing.get("data")
    if not isinstance(data, list):
        raise GraphProtocolError("Media list is not a list")
    media: list[AccountMedia] = []
    for item in data[:limit]:
        if not isinstance(item, dict) or not str(item.get("id", "")).isdigit():
            raise GraphProtocolError("Unsupported media item")
        kind = _format(item)
        requested = [*BASE_METRICS, *(["ig_reels_avg_watch_time"] if kind == "reel" else [])]
        metrics: list[GraphMetric] = []
        error: str | None = None
        try:
            body = graph_request(
                transport, "GET", f"/{item['id']}/insights", {"metric": ",".join(requested)}
            )
            metrics = parse_metrics(body, requested)
        except GraphRateLimitError:
            raise
        except GraphAPIError as refused:
            # e.g. posts made before the account became professional have no insights.
            error = f"code={refused.code}, subcode={refused.subcode}"
        media.append(
            AccountMedia(
                id=str(item["id"]),
                format=kind,
                posted_at=datetime.fromisoformat(str(item["timestamp"])),
                permalink=str(item.get("permalink", "")),
                caption=str(item.get("caption", ""))[:200],
                like_count=_count(item.get("like_count")),
                comments_count=_count(item.get("comments_count")),
                metrics=metrics,
                insights_error=error,
            )
        )
    return AccountSnapshot(
        account_id=account_id,
        username=str(profile.get("username", "")),
        account_type=str(profile.get("account_type", "")),
        followers=_count(profile.get("followers_count")),
        media_count=_count(profile.get("media_count")),
        api_version=config.api_version,
        observed_at=now(),
        media=media,
    )


class AccountStore:
    """NFR-06: separate SQLite file; snapshots are appended, never edited."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, snapshot: AccountSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS snapshot (observed_at TEXT PRIMARY KEY, "
                "account_id TEXT NOT NULL, snapshot_json TEXT NOT NULL)"
            )
            db.execute(
                "INSERT OR IGNORE INTO snapshot VALUES (?, ?, ?)",
                (
                    snapshot.observed_at.isoformat(),
                    snapshot.account_id,
                    snapshot.model_dump_json(),
                ),
            )

    def latest(self) -> AccountSnapshot | None:
        if not self.path.is_file():
            return None
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT snapshot_json FROM snapshot ORDER BY observed_at DESC LIMIT 1"
            ).fetchone()
        return AccountSnapshot.model_validate_json(row[0]) if row else None


def _group(rows: Sequence[tuple[str, float]], order: list[str]) -> list[JsonValue]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for key, value in rows:
        grouped[key].append(value)
    return [
        {"key": key, "posts": len(grouped[key]), "median": median(grouped[key])}
        for key in order
        if key in grouped
    ]


def analyze(snapshot: AccountSnapshot) -> dict[str, JsonValue]:
    """FR-11: medians per format, weekday and Cairo time band, with the post count beside each.

    Medians resist one viral post; small counts are shown, not hidden, so the owner can judge.
    """
    rated = [(m, m.engagement_rate) for m in snapshot.media]
    known = [(m, rate) for m, rate in rated if rate is not None]
    reach = [(m.format, v.value) for m in snapshot.media for v in m.metrics if v.name == "reach"]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    bands = ["morning 06-12", "afternoon 12-17", "evening 17-22", "night 22-06"]

    def band(at: datetime) -> str:
        hour = at.astimezone(CAIRO).hour
        return bands[sum(hour >= h for h in (12, 17, 22)) if hour >= 6 else 3]

    formats = ["reel", "carousel", "photo", "other"]
    return {
        "posts": len(snapshot.media),
        "with_insights": sum(1 for m in snapshot.media if m.metrics),
        "engagement_by_format": _group([(m.format, r) for m, r in known], formats),
        "reach_by_format": _group(reach, formats),
        "engagement_by_day": _group(
            [(days[m.posted_at.astimezone(CAIRO).weekday()], r) for m, r in known], days
        ),
        "engagement_by_time": _group([(band(m.posted_at), r) for m, r in known], bands),
    }


def view(snapshot: AccountSnapshot) -> dict[str, JsonValue]:
    """FR-11: dashboard payload: the snapshot, per-post engagement and the summary."""
    data: dict[str, JsonValue] = json.loads(snapshot.model_dump_json())
    data["media"] = [
        {**json.loads(m.model_dump_json()), "engagement_rate": m.engagement_rate}
        for m in snapshot.media
    ]
    data["analysis"] = analyze(snapshot)
    return data


SAMPLE_CAPTIONS = {
    "reel": [
        "Morning swim at the house reef",
        "Sunset from the pier",
        "A slow tour of the pool deck",
    ],
    "carousel": [
        "Five corners of the resort",
        "What breakfast looks like here",
        "Rooms, from door to view",
    ],
    "photo": ["Evening light on the lounge", "Palm shade by the pool", "Dinner under the stars"],
}


def sample_snapshot(now: datetime, seed: int = 7) -> AccountSnapshot:
    """NFR-07: invented demo numbers for an empty account; labelled Sample everywhere shown.

    Rough shape only (reels reach more, carousels get saved more); not a forecast.
    """
    rng = random.Random(seed)
    base = {"reel": 1800.0, "carousel": 900.0, "photo": 600.0}
    rates = {
        "reel": (0.055, 0.004, 0.012, 0.02),
        "carousel": (0.065, 0.006, 0.03, 0.008),
        "photo": (0.05, 0.004, 0.012, 0.005),
    }
    media: list[AccountMedia] = []
    for index in range(24):
        kind: Format = rng.choice(["reel", "reel", "carousel", "photo"])
        posted = (now - timedelta(days=2 + index * 2.3)).replace(
            hour=rng.choice([7, 9, 13, 16, 18, 19, 20, 21, 23]), minute=0, second=0, microsecond=0
        ) - timedelta(hours=3)
        reach = round(base[kind] * rng.lognormvariate(0, 0.45))
        like, comment, save, share = (
            max(0, round(reach * r * rng.uniform(0.6, 1.5))) for r in rates[kind]
        )
        views = round(reach * (2.4 if kind == "reel" else 1.5) * rng.uniform(0.9, 1.2))
        values = {
            "views": views,
            "reach": reach,
            "likes": like,
            "comments": comment,
            "saved": save,
            "shares": share,
        }
        metrics = [GraphMetric(name=name, value=value) for name, value in values.items()]  # type: ignore[arg-type]
        if kind == "reel":
            metrics.append(
                GraphMetric(name="ig_reels_avg_watch_time", value=rng.randint(3500, 9000))
            )
        media.append(
            AccountMedia(
                id=str(900000 + index),
                format=kind,
                posted_at=posted,
                caption=rng.choice(SAMPLE_CAPTIONS[kind]),
                like_count=like,
                comments_count=comment,
                metrics=metrics,
            )
        )
    return AccountSnapshot(
        account_id="900000",
        username="sample_resort",
        account_type="BUSINESS",
        followers=2480,
        media_count=len(media),
        api_version="sample",
        observed_at=now,
        media=media,
    )
