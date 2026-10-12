"""FR-14, NFR-04, NFR-07: all metric paths run offline without application approvals."""

import csv
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import instabay.benchmarks.harness as harness
from instabay.adapters.call_store import CallRecord
from instabay.adapters.fixture_fidelity import content_signature
from instabay.adapters.publisher import DryRunPublisher
from instabay.benchmarks.efficiency import efficiency_metric
from instabay.benchmarks.humans import (
    DIMENSIONS,
    BlindItem,
    TranslationCase,
    arabic_metric,
    autonomy_metric,
    blind_packet,
    brand_metric,
    write_packet,
)
from instabay.benchmarks.models import BenchmarkResults, ContentEvidence, PriceCard
from instabay.benchmarks.readme import END, START, render_table, update_readme
from instabay.cli import app
from instabay.repository import Repository


@pytest.fixture(scope="module")
def benchmark(tmp_path_factory):
    root = tmp_path_factory.mktemp("benchmark")
    with pytest.MonkeyPatch.context() as patch:

        def forbidden(*args, **kwargs):
            raise AssertionError("Benchmark must never approve or publish")

        patch.setattr(Repository, "approve", forbidden)
        patch.setattr(DryRunPublisher, "publish", forbidden)
        result = harness.run_benchmark(
            output=root / "results.json", artifacts=root / "artifacts", ratings=root / "ratings"
        )
    content = [
        ContentEvidence.model_validate(row)
        for row in json.loads((root / "artifacts/content.json").read_text())
    ]
    items = [
        BlindItem.model_validate(row)
        for row in json.loads((root / "artifacts/human_packet/arabic_key_private.json").read_text())
    ]
    calls = [
        CallRecord.model_validate_json(line)
        for line in (root / "artifacts/calls.jsonl").read_text().splitlines()
    ]
    return root, result, content, items, calls


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_full_five_metric_protocol_and_missing_human_data(benchmark) -> None:
    root, result, content, items, calls = benchmark
    assert BenchmarkResults.model_validate_json((root / "results.json").read_bytes()) == result
    assert result.corpus_posts == 21
    assert result.brand_consistency.judge_mean.mean == pytest.approx(4.6)
    assert result.brand_consistency.negative_control_mean.mean == pytest.approx(2.2)
    assert result.brand_consistency.negative_control_clearly_lower
    assert result.brand_consistency.quadratic_weighted_kappa is None
    assert result.arabic_quality.native_mean is None
    assert result.arabic_quality.krippendorff_alpha_interval is None
    assert result.autonomy.human_minutes_per_week is None
    assert result.autonomy.measured_full_pipeline_automation_share is None
    assert result.autonomy.configured_automation_share == 7 / 8
    assert len(result.optimization_uplift.seed_results) == 120
    assert result.optimization_uplift.seeds == list(range(20))
    assert result.optimization_uplift.evaluation_weeks == [9, 10, 11, 12]
    assert result.optimization_uplift.summaries["oracle"].cumulative_regret.mean == 0
    assert len(content) == 21 and len(items) == 40
    assert sum(item.version == "native" for item in items) == 20
    assert len(calls) == 222
    assert result.efficiency.benchmark_evaluation_calls == 93
    feed = result.efficiency.groups["feed"]
    reel = result.efficiency.groups["reel_concept"]
    assert (feed.posts, feed.input_tokens, feed.output_tokens, feed.calls) == (18, 19440, 8820, 108)
    assert reel.posts == 3 and reel.calls == 18
    assert feed.paid_list_price_usd is None and feed.actual_spend_usd == 0
    assert all(row.latency_ms >= 0 for row in calls)
    assert {r.run_id for r in calls if r.template_name == "judge"} >= {
        "benchmark-negative-controls"
    }


def test_real_human_csv_ingestion_and_price_arithmetic(benchmark, tmp_path: Path) -> None:
    _, result, content, items, calls = benchmark
    brand_rows = [
        {
            "post_id": row.post.id,
            "content_signature": content_signature(row.post),
            "rater_id": "synthetic-rater",
            **{name: getattr(row.review.judge.samples[0].scores, name) for name in DIMENSIONS},
        }
        for row in content[:20]
    ]
    write_csv(tmp_path / "brand_synthetic.csv", brand_rows)
    arabic_rows = [
        {
            "item_id": item.item_id,
            "content_signature": item.content_signature,
            "rater_id": rater,
            "fluency": 5 if item.version == "native" else 3,
            "naturalness": 4 if item.version == "native" else 3,
            "brand_voice": 5 if item.version == "native" else 3,
        }
        for item in items
        for rater in ("synthetic-a", "synthetic-b")
    ]
    write_csv(tmp_path / "arabic_synthetic.csv", arabic_rows)
    approval_rows = [
        {
            "post_id": row.post.id,
            "content_signature": content_signature(row.post),
            "decision": "APPROVED" if index >= 3 else "EDITED",
            "seconds_spent": 30,
            "reason": "Synthetic measurement data only",
        }
        for index, row in enumerate(content)
    ]
    write_csv(tmp_path / "approval_synthetic.csv", approval_rows)
    brand = brand_metric(content, [2.2] * 10, tmp_path)
    arabic = arabic_metric(content, items, tmp_path)
    autonomy = autonomy_metric(content, tmp_path)
    assert brand.labeled_posts == 20 and brand.quadratic_weighted_kappa == 1
    assert arabic.native_mean.mean == pytest.approx(14 / 3)
    assert arabic.mt_mean.mean == 3 and arabic.native_win_rate.mean == 1
    assert arabic.krippendorff_alpha_interval == 1
    assert arabic.judge_human_spearman is None  # Constant canned scores.
    assert arabic.raters == 2 and arabic.paired_posts == 20
    assert autonomy.first_pass_approval_rate.mean == pytest.approx(18 / 21)
    assert autonomy.human_minutes_per_week.mean == 3.5
    assert autonomy.measured_full_pipeline_automation_share is None
    card = PriceCard(
        model="fake-fixture-v1",
        input_usd_per_million=1,
        output_usd_per_million=2,
        source="synthetic arithmetic test",
        verified_on="2026-10-12",
    )
    efficiency = efficiency_metric(content, calls, [card])
    assert efficiency.groups["feed"].paid_list_price_usd == pytest.approx((19440 + 8820 * 2) / 1e6)
    paid_result = result.model_copy(update={"efficiency": efficiency})
    assert "$0.0021/post" in render_table(paid_result)


def test_blind_packet_and_template_ratings_are_preserved(benchmark, tmp_path: Path) -> None:
    _, _, content, items, _ = benchmark
    write_packet(tmp_path, content, items)
    blind = json.loads((tmp_path / "arabic_blind_items.json").read_text())
    assert all(set(row) == {"item_id", "caption"} for row in blind)
    assert [item.version for item in items] != ["native", "mt"] * 20
    path = tmp_path / "arabic_template.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0].update(rater_id="synthetic-a", fluency="5", naturalness="4", brand_voice="5")
    write_csv(path, rows)
    existing = path.read_bytes()
    write_packet(tmp_path, content, items)
    assert path.read_bytes() == existing
    assert arabic_metric(content, items, tmp_path).rated_items == 1


def test_invalid_partial_duplicate_and_stale_ratings_fail(benchmark, tmp_path: Path) -> None:
    _, _, content, items, _ = benchmark
    row = {
        "item_id": items[0].item_id,
        "content_signature": items[0].content_signature,
        "rater_id": "synthetic-a",
        "fluency": 5,
        "naturalness": 4,
        "brand_voice": "",
    }
    path = tmp_path / "arabic_cases.csv"
    write_csv(path, [row])
    with pytest.raises(ValueError, match="Partially filled"):
        arabic_metric(content, items, tmp_path)
    row["brand_voice"] = 5
    write_csv(path, [row, row])
    with pytest.raises(ValueError, match="Duplicate"):
        arabic_metric(content, items, tmp_path)
    row["content_signature"] = "a" * 64
    write_csv(path, [row])
    with pytest.raises(ValueError, match="exact blind caption"):
        arabic_metric(content, items, tmp_path)


def test_checkpoint_resume_truncation_and_summary_validation(
    benchmark, tmp_path: Path, monkeypatch
) -> None:
    root, result, _, _, _ = benchmark
    records = [
        harness.SeedCheckpoint.model_validate_json(line)
        for line in (root / "artifacts/seed-checkpoints.jsonl").read_text().splitlines()
    ]
    cache = tmp_path / "seeds.jsonl"
    cache.write_text(records[0].model_dump_json() + "\n{truncated")
    called = []

    def replay(brand, seed):
        called.append(seed)
        return records[seed].results, records[seed].evidence

    monkeypatch.setattr(harness, "evaluate_seed", replay)
    from tests.support import demo_brand

    resumed = harness.optimization_checkpoint(demo_brand(), result.protocol_hash, cache)
    assert called == list(range(1, 20))
    assert resumed == result.optimization_uplift.seed_results
    called.clear()
    assert harness.optimization_checkpoint(demo_brand(), result.protocol_hash, cache) == resumed
    assert called == []
    payload = records[0].model_dump()
    payload["results"][0]["late_rate"] = 0.99
    with pytest.raises(ValueError, match="summary"):
        harness.SeedCheckpoint.model_validate(payload)


def test_cli_and_readme_generation_do_not_touch_other_text(benchmark, tmp_path: Path) -> None:
    root, expected, _, _, _ = benchmark
    readme = tmp_path / "README.md"
    readme.write_text(f"Preamble\n{START}\nold\n{END}\nFooter\n")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(
        app,
        [
            "bench",
            "--output",
            str(output),
            "--artifacts",
            str(root / "artifacts"),
            "--ratings",
            str(tmp_path / "empty-ratings"),
            "--readme",
            str(readme),
        ],
    )
    assert result.exit_code == 0, result.exception
    actual = BenchmarkResults.model_validate_json(output.read_bytes())
    assert actual.optimization_uplift == expected.optimization_uplift
    assert readme.read_text() == f"Preamble\n{START}\n{render_table(actual)}\n{END}\nFooter\n"
    assert "HUMAN:" in result.output
    readme.write_text("No markers")
    with pytest.raises(ValueError, match="marker"):
        update_readme(readme, output)
    assert readme.read_text() == "No markers"


def test_recorded_mt_metadata_and_exact_english_binding(benchmark) -> None:
    _, _, content, _, _ = benchmark
    payload = json.loads(Path("bench/fixtures/translations.json").read_text())
    with pytest.raises(ValueError, match="source hash"):
        TranslationCase.model_validate({**payload[0], "provenance": "recorded_mt"})
    cases = [
        TranslationCase.model_validate(
            {
                **row,
                "provenance": "recorded_mt",
                "model": "synthetic-test-mt",
                "recorded_at": "2026-10-12T00:00:00Z",
                "english_source_hash": hashlib.sha256(
                    content[index].post.en.caption.encode()
                ).hexdigest(),
            }
        )
        for index, row in enumerate(payload)
    ]
    packet = blind_packet(content, cases)
    assert all(item.provenance == "recorded_mt" for item in packet if item.version == "mt")
    cases[0] = cases[0].model_copy(update={"english_source_hash": "a" * 64})
    with pytest.raises(ValueError, match="exact English"):
        blind_packet(content, cases)


def test_benchmark_rejects_live_environment_before_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    output = tmp_path / "results.json"
    result = CliRunner().invoke(app, ["bench", "--output", str(output)])
    assert result.exit_code == 2
    assert "offline dry_run" in result.output
    assert not output.exists()
