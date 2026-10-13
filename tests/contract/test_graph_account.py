"""FR-11: read-only account snapshot: GET only, refused insights kept, nothing learned."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_socket
from fastapi.testclient import TestClient

from instabay.adapters.graph_account import (
    ACCOUNT_DB,
    AccountSnapshot,
    AccountStore,
    analyze,
    fetch_account,
    sample_snapshot,
)
from instabay.adapters.graph_models import GraphRateLimitError
from instabay.adapters.graph_transport import FixtureGraphTransport
from instabay.dashboard.app import create_app
from tests.graph_support import FIXTURES, GRAPH_CONFIG
from tests.support import demo_brand

NOW = datetime(2026, 10, 13, 9, tzinfo=UTC)


def snapshot() -> AccountSnapshot:
    transport = FixtureGraphTransport(FIXTURES / "account.json")
    result = fetch_account(transport, GRAPH_CONFIG, "1000", now=lambda: NOW)
    transport.assert_consumed()
    assert all(method == "GET" for method, _, _ in transport.calls)
    return result


def test_reads_profile_posts_and_insights_and_keeps_refused_posts() -> None:
    account = snapshot()
    assert (account.username, account.followers, len(account.media)) == ("instabay_test", 412, 3)
    photo, reel, old = account.media
    assert (photo.format, reel.format, old.format) == ("photo", "reel", "carousel")
    assert photo.engagement_rate == pytest.approx(50 / 500)
    assert reel.engagement_rate == pytest.approx(130 / 1000)
    assert old.metrics == [] and old.insights_error == "code=100, subcode=2108006"
    assert old.engagement_rate is None


def test_rate_limit_stops_the_read() -> None:
    transport = FixtureGraphTransport(FIXTURES / "account_rate_limit.json")
    with pytest.raises(GraphRateLimitError):
        fetch_account(transport, GRAPH_CONFIG, "1000", now=lambda: NOW)


def test_analysis_uses_medians_with_counts_in_cairo_time() -> None:
    summary = analyze(snapshot())
    assert summary["posts"] == 3 and summary["with_insights"] == 2
    assert summary["engagement_by_format"] == [
        {"key": "reel", "posts": 1, "median": pytest.approx(0.13)},
        {"key": "photo", "posts": 1, "median": pytest.approx(0.1)},
    ]
    # 15:30 UTC on Friday is 18:30 in Cairo; 06:00 UTC Saturday is 09:00.
    assert [r["key"] for r in summary["engagement_by_time"]] == ["morning 06-12", "evening 17-22"]  # type: ignore[index, union-attr]
    assert [r["key"] for r in summary["engagement_by_day"]] == ["Fri", "Sat"]  # type: ignore[index, union-attr]


def test_snapshots_are_appended_and_the_dashboard_shows_the_latest(tmp_path: Path) -> None:
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    store = AccountStore(tmp_path / ACCOUNT_DB)
    assert store.latest() is None
    first = snapshot()
    store.save(first)
    later = datetime(2026, 10, 14, tzinfo=UTC)
    store.save(first.model_copy(update={"followers": 500, "observed_at": later}))
    assert store.latest().followers == 500  # type: ignore[union-attr]
    runs = tmp_path / "outputs"
    runs.mkdir(exist_ok=True)
    client = TestClient(
        create_app(workspace=tmp_path / "ws", brand=demo_brand(), runs=runs, root=tmp_path)
    )
    body = client.get("/api/instagram").json()
    assert body["connected"] and body["username"] == "instabay_test"
    assert body["media"][1]["engagement_rate"] == pytest.approx(0.13)
    assert client.get("/api/summary").json()["instagram"]["username"] == "instabay_test"


def test_sample_data_is_labelled_deterministic_and_never_stored(tmp_path: Path) -> None:
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    first, again = sample_snapshot(NOW), sample_snapshot(NOW)
    assert first == again and len(first.media) == 24
    assert first.api_version == "sample" and all(m.engagement_rate for m in first.media)
    runs = tmp_path / "outputs"
    runs.mkdir()
    client = TestClient(
        create_app(workspace=tmp_path / "ws", brand=demo_brand(), runs=runs, root=tmp_path)
    )
    assert client.get("/api/instagram").json() == {"connected": False}
    body = client.get("/api/instagram?sample=1").json()
    assert body["sample"] is True and body["analysis"]["with_insights"] == 24
    assert not (tmp_path / ACCOUNT_DB).exists()
