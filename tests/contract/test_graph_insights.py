"""FR-11: synthetic modern insights, absent values, zero reach and reel watch units."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlmodel import Session, select

from instabay.adapters.graph_insights import GraphInsights
from instabay.adapters.graph_transport import FixtureGraphTransport
from instabay.core.tables import GraphObservationRow, MetricRow, PosteriorRow
from instabay.repository import Repository
from tests.graph_support import FIXTURES, GRAPH_CONFIG, live_post, publisher


@pytest.mark.parametrize(
    "scenario,count,rate",
    [
        ("insights", 6, 0.13),
        ("insights_empty", 0, None),
        ("insights_partial", 1, None),
        ("insights_zero", 6, None),
        ("insights_overlap", 6, 1.6),
        ("insights_reel", 7, 0.13),
    ],
)
def test_ingests_missing_without_zeros_and_raw_overlap_without_bandit_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, count: int, rate: float | None
) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = live_post(repository, "reel" if scenario == "insights_reel" else "photo")
        publish, contract = publisher(
            repository, "reel" if scenario == "insights_reel" else "finished"
        )
        publish.publish(post.id)
        contract.assert_consumed()
        for _ in range(2):
            transport = FixtureGraphTransport(FIXTURES / f"{scenario}.json")
            insights = GraphInsights(
                repository,
                GRAPH_CONFIG,
                transport,
                account_id="1000",
                confirm_live=True,
                now=lambda: datetime(2026, 10, 14, tzinfo=UTC),
            )
            batch = insights.fetch(post.id)
            transport.assert_consumed()
            assert len(batch.metrics) == count
            assert batch.engagement_rate == rate
            assert "watch_through" not in batch.model_dump()
            if scenario == "insights_reel":
                assert (
                    next(m.value for m in batch.metrics if m.name == "ig_reels_avg_watch_time")
                    == 4123.5
                )
        with Session(repository.engine) as session:
            assert len(session.exec(select(MetricRow)).all()) == count
            assert len(session.exec(select(GraphObservationRow)).all()) == 1
            assert session.exec(select(PosteriorRow)).all() == []
    finally:
        repository.close()


@pytest.mark.parametrize(
    "data",
    [
        None,
        [{"name": "plays", "values": [{"value": 1}]}],
        [{"name": "reach", "values": [{"value": True}]}],
        [{"name": "reach", "values": [{"value": -1}]}],
        [{"name": "reach", "values": [{"value": 1.5}]}],
        [{"name": "reach", "values": [{"value": 1}, {"value": 2}]}],
        [{"name": "reach", "period": "day", "values": [{"value": 1}]}],
        [{"name": "reach", "values": [{"value": 1}]}] * 2,
    ],
)
def test_malformed_metrics_fail_atomically_without_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: object
) -> None:
    from instabay.adapters.graph_models import GraphProtocolError
    from instabay.adapters.graph_transport import GraphResponse

    monkeypatch.setenv("INSTABAY_MODE", "live")
    repository = Repository(tmp_path / "state.sqlite")
    try:
        post = live_post(repository)
        engine, transport = publisher(repository, "finished")
        engine.publish(post.id)
        transport.assert_consumed()

        class Malformed:
            def request(self, method: str, path: str, params: dict[str, str]) -> GraphResponse:
                return GraphResponse.model_validate(
                    {
                        "status_code": 200,
                        "body": {"data": data}
                        if path.endswith("insights")
                        else {"media_type": "IMAGE"},
                    }
                )

        insights = GraphInsights(
            repository, GRAPH_CONFIG, Malformed(), account_id="1000", confirm_live=True
        )
        with pytest.raises(GraphProtocolError):
            insights.fetch(post.id)
        with Session(repository.engine) as session:
            assert session.exec(select(MetricRow)).all() == []
            assert session.exec(select(GraphObservationRow)).all() == []
    finally:
        repository.close()
