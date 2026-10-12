"""FR-14: ledger-based cold pipeline usage, measured local timing and explicit price gaps."""

from typing import Literal

from instabay.adapters.call_store import CallRecord
from instabay.benchmarks.models import ContentEvidence, EfficiencyGroup, EfficiencyMetric, PriceCard
from instabay.benchmarks.statistics import bootstrap, percentile


def paid_cost(calls: list[CallRecord], cards: list[PriceCard]) -> float | None:
    """FR-14: missing prices are missing values, never a fictitious zero-priced provider."""
    index = {card.model: card for card in cards}
    if len(index) != len(cards):
        raise ValueError("Duplicate price-card model")
    charged = [call for call in calls if call.status != "cached"]
    if any(call.model not in index for call in charged):
        return None
    return sum(
        (
            call.input_tokens * index[call.model].input_usd_per_million
            + call.output_tokens * index[call.model].output_usd_per_million
        )
        / 1_000_000
        for call in charged
    )


def efficiency_metric(
    content: list[ContentEvidence], all_calls: list[CallRecord], cards: list[PriceCard]
) -> EfficiencyMetric:
    """FR-14: separate brand setup and benchmark evaluators from per-post pipeline costs."""
    groups: dict[Literal["feed", "reel_concept"], EfficiencyGroup] = {}
    for name in ("feed", "reel_concept"):
        rows = [row for row in content if (row.post.format == "reel") == (name == "reel_concept")]
        if not rows:
            continue
        ledgers = [[call for call in row.calls if call.status != "cached"] for row in rows]
        inputs = [sum(call.input_tokens for call in calls) for calls in ledgers]
        outputs = [sum(call.output_tokens for call in calls) for calls in ledgers]
        actual = [sum(call.cost_usd for call in calls) for calls in ledgers]
        paid = [paid_cost(calls, cards) for calls in ledgers]
        known_paid = [value for value in paid if value is not None]
        wall = [row.wall_latency_ms for row in rows]
        provider = [sum(call.latency_ms for call in calls) for calls in ledgers]
        groups[name] = EfficiencyGroup(
            posts=len(rows),
            input_tokens=sum(inputs),
            output_tokens=sum(outputs),
            calls=sum(len(calls) for calls in ledgers),
            actual_spend_usd=sum(actual),
            paid_list_price_usd=sum(known_paid) if len(known_paid) == len(rows) else None,
            mean_input_tokens=bootstrap([float(value) for value in inputs]),
            mean_output_tokens=bootstrap([float(value) for value in outputs]),
            mean_actual_spend_usd=bootstrap(actual),
            mean_paid_list_price_usd=bootstrap(known_paid)
            if len(known_paid) == len(rows)
            else None,
            mean_wall_latency_ms=bootstrap(wall),
            wall_p50_ms=percentile(wall, 0.5),
            wall_p95_ms=percentile(wall, 0.95),
            provider_sum_p50_ms=percentile(provider, 0.5),
            provider_sum_p95_ms=percentile(provider, 0.95),
        )
    shared = [
        call
        for call in all_calls
        if call.template_name == "brand_architect" and call.status != "cached"
    ]
    evaluation = [
        call
        for call in all_calls
        if (call.run_id or "").startswith("benchmark-") and call.status != "cached"
    ]
    return EfficiencyMetric(
        groups=groups,
        shared_brand_input_tokens=sum(call.input_tokens for call in shared),
        shared_brand_output_tokens=sum(call.output_tokens for call in shared),
        shared_brand_actual_spend_usd=sum(call.cost_usd for call in shared),
        benchmark_evaluation_calls=len(evaluation),
        benchmark_evaluation_input_tokens=sum(call.input_tokens for call in evaluation),
        benchmark_evaluation_output_tokens=sum(call.output_tokens for call in evaluation),
        price_cards=cards,
        missing_price_models=sorted(
            {call.model for call in all_calls if call.status != "cached"}
            - {card.model for card in cards}
        ),
        provenance="Cold FakeLLM: fixture tokens, actual spend zero, local wall timing; "
        "no video render or real-provider latency",
    )
