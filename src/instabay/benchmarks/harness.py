"""FR-14: run the five-metric offline benchmark without approving or publishing drafts."""

import hashlib
import json
import math
import os
import platform
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from typing import Self

import yaml
from pydantic import TypeAdapter, model_validator

from instabay.benchmarks.corpus import Corpus, replay_corpus
from instabay.benchmarks.efficiency import efficiency_metric
from instabay.benchmarks.humans import (
    TranslationCase,
    arabic_metric,
    autonomy_metric,
    blind_packet,
    brand_metric,
    write_packet,
)
from instabay.benchmarks.models import BenchmarkResults, PriceCard
from instabay.benchmarks.policies import POLICIES, PolicyWeek, SeedResult, evaluate_seed, summarize
from instabay.core.schemas import Boundary, BrandConstitution, BrandInput, Hash
from instabay.db import SQLiteCallStore


class SeedCheckpoint(Boundary):
    """FR-14, NFR-03: one flushed complete seed, including every policy/week intermediate."""

    protocol_hash: Hash
    seed: int
    results: list[SeedResult]
    evidence: list[PolicyWeek]

    @model_validator(mode="after")
    def complete_seed(self) -> Self:
        if len(self.results) != 6 or {row.policy for row in self.results} != set(POLICIES):
            raise ValueError("Checkpoint needs six unique policies")
        expected = {(policy, week) for policy in POLICIES for week in range(1, 13)}
        if len(self.evidence) != 72 or {(r.policy, r.week) for r in self.evidence} != expected:
            raise ValueError("Checkpoint needs twelve complete weeks for every policy")
        for row in self.evidence:
            if row.seed != self.seed or any(
                len(values) != 7 for values in (row.rates, row.planned, row.executed)
            ):
                raise ValueError("Checkpoint evidence is incomplete")
        for summary in self.results:
            history = sorted(
                [row for row in self.evidence if row.policy == summary.policy], key=lambda r: r.week
            )
            late = mean(value for row in history[-4:] for value in row.rates)
            regret = sum(row.regret for row in history)
            if (
                summary.seed != self.seed
                or not math.isclose(summary.late_rate, late, abs_tol=1e-12)
                or not math.isclose(summary.cumulative_regret, regret, abs_tol=1e-12)
            ):
                raise ValueError("Checkpoint summary does not match its evidence")
        return self


def protocol_hash(root: Path) -> str:
    """NFR-03: cache identity includes code, frozen audience, corpus, fixtures and Python."""
    paths = [
        *sorted((root / "src/instabay/benchmarks").glob("*.py")),
        root / "src/instabay/core/optimizer.py",
        root / "src/instabay/core/planner.py",
        root / "src/instabay/core/schemas.py",
        root / "sim/world.py",
        root / "bench/corpus.json",
        root / "bench/fixtures/translations.json",
        root / "bench/fixtures/negative_controls.json",
        root / "tests/fixtures/llm/cycle-catalog.json",
        root / "tests/fixtures/llm/brand_architect__brand-draft.json",
        root / "config/brand_inputs.example.yaml",
        *sorted((root / "bench/fixtures/llm").glob("*.json")),
        *sorted((root / "src/instabay/prompts").glob("*.md")),
    ]
    digest = hashlib.sha256(sys.version.encode())
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    digest.update(b"12-weeks:7-posts:20-seeds:2000-bootstrap:hook-drift-0.2-v1")
    return digest.hexdigest()


def optimization_checkpoint(
    brand: BrandConstitution,
    identity: str,
    path: Path,
    notify_progress: Callable[[str], None] | None = None,
) -> list[SeedResult]:
    """FR-14: resume flushed complete seeds; interrupted trailing JSON is safely replaced."""
    completed: dict[int, SeedCheckpoint] = {}
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            try:
                record = SeedCheckpoint.model_validate_json(line)
            except ValueError:
                if index == len(lines) - 1:
                    break
                raise ValueError("Corrupt benchmark checkpoint before its last line") from None
            if record.protocol_hash == identity:
                if record.seed in completed or not 0 <= record.seed < 20:
                    raise ValueError("Duplicate or invalid benchmark checkpoint seed")
                if {row.policy for row in record.results} != {
                    "fixed",
                    "uniform",
                    "thompson",
                    "oracle",
                    "leak_unguarded",
                    "leak_guarded",
                } or any(row.seed != record.seed for row in record.results):
                    raise ValueError("Incomplete seed checkpoint")
                completed[record.seed] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    # Rewrite only valid records for this exact protocol; drop truncated/obsolete records.
    path.write_text(
        "".join(completed[seed].model_dump_json() + "\n" for seed in sorted(completed)),
        encoding="utf-8",
    )
    for seed in range(20):
        if seed in completed:
            continue
        results, evidence = evaluate_seed(brand, seed)
        record = SeedCheckpoint(
            protocol_hash=identity, seed=seed, results=results, evidence=evidence
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        completed[seed] = record
        if notify_progress and (seed + 1) % 5 == 0:
            notify_progress(f"Optimization: {seed + 1}/20 complete world seeds")
    return [row for seed in sorted(completed) for row in completed[seed].results]


def run_benchmark(
    root: Path = Path("."),
    output: Path = Path("bench/results.json"),
    artifacts: Path = Path("outputs/bench"),
    ratings: Path = Path("bench/human_ratings"),
    prices: Path | None = None,
    notify_progress: Callable[[str], None] | None = None,
) -> BenchmarkResults:
    """FR-14: missing HUMAN data remains null; no API keys, approvals, GPU or live adapters."""
    corpus = Corpus.model_validate_json((root / "bench/corpus.json").read_bytes())
    corpus_digest = hashlib.sha256((root / "bench/corpus.json").read_bytes()).hexdigest()
    inputs = BrandInput.model_validate(
        yaml.safe_load((root / "config/brand_inputs.example.yaml").read_text())
    )
    translations = TypeAdapter(list[TranslationCase]).validate_json(
        (root / "bench/fixtures/translations.json").read_bytes()
    )
    cards = TypeAdapter(list[PriceCard]).validate_json(prices.read_bytes()) if prices else []
    identity = protocol_hash(root)
    artifacts.mkdir(parents=True, exist_ok=True)
    # Cold calls are measured in disposable state on every run, never in a human's queue.
    with (
        TemporaryDirectory(prefix="instabay-bench-") as temp,
        SQLiteCallStore(Path(temp) / "calls.sqlite") as store,
    ):
        brand, content, controls = replay_corpus(
            corpus, inputs, store, root / "tests/fixtures/llm", root / "bench/fixtures/llm"
        )
        calls = store.calls()
    (artifacts / "content.json").write_text(
        json.dumps([row.model_dump(mode="json") for row in content], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (artifacts / "calls.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in calls), encoding="utf-8"
    )
    packet = blind_packet(content, translations)
    packet_path = artifacts / "human_packet" / corpus_digest[:12]
    write_packet(packet_path, content, packet)
    brand_results = brand_metric(content, controls, ratings)
    arabic_results = arabic_metric(content, packet, ratings)
    autonomy = autonomy_metric(content, ratings)
    efficiency = efficiency_metric(content, calls, cards)
    seed_results = optimization_checkpoint(
        brand, identity, artifacts / "seed-checkpoints.jsonl", notify_progress
    )
    optimization = summarize(seed_results)
    pending = []
    pending.append(f"HUMAN: rating packet and blank templates at {packet_path}")
    if brand_results.calibration_status != "human_labels_available":
        pending.append(
            "HUMAN: label 20 brand posts for judge kappa; canned scores are uncalibrated"
        )
    if arabic_results.status != "human_labels_available" or arabic_results.raters < 2:
        pending.append(
            "HUMAN: blind-rate 20 native + 20 comparison captions with at least two Arabic raters"
        )
    if any(case.provenance != "recorded_mt" for case in translations):
        pending.append(
            "HUMAN: replace authored comparison fixtures with recorded real MT "
            "before claiming native-vs-MT quality"
        )
    if not autonomy.touchpoints or len(autonomy.touchpoints) != 21:
        pending.append(
            "HUMAN: provide timed first-pass review feedback; bench never stores approvals"
        )
    if efficiency.missing_price_models:
        pending.append(
            "HUMAN: provide verified paid list-price cards for real runs; FakeLLM has no provider"
        )
    result = BenchmarkResults(
        generated_at=datetime.now(UTC),
        protocol_hash=identity,
        corpus_hash=corpus_digest,
        corpus_posts=len(content),
        environment={
            "python": platform.python_version(),
            "platform": platform.system(),
            "machine": platform.machine(),
            "timing": "cold local fixture replay; varies by host and run",
        },
        brand_consistency=brand_results,
        arabic_quality=arabic_results,
        optimization_uplift=optimization,
        efficiency=efficiency,
        autonomy=autonomy,
        human_pending=pending,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result
