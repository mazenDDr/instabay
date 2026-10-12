"""FR-14: README benchmark numbers come only from validated results JSON."""

from pathlib import Path

from instabay.benchmarks.models import BenchmarkResults
from instabay.benchmarks.statistics import Estimate

START = "<!-- BENCHMARK:START -->"
END = "<!-- BENCHMARK:END -->"


def interval(value: Estimate, percent: bool = False) -> str:
    scale = 100 if percent else 1
    unit = "%" if percent else ""
    return f"{value.mean * scale:.2f}{unit} [{value.low * scale:.2f}, {value.high * scale:.2f}]"


def render_table(result: BenchmarkResults) -> str:
    """FR-14: pending ratings and price gaps are visible beside all illustrative results."""
    brand = result.brand_consistency
    arabic = result.arabic_quality
    efficiency = result.efficiency
    autonomy = result.autonomy
    human_arabic = interval(arabic.native_mean) if arabic.native_mean else "Pending human ratings"
    human_mt = interval(arabic.mt_mean) if arabic.mt_mean else "pending"
    human_win = interval(arabic.native_win_rate, True) if arabic.native_win_rate else "pending"
    alpha = (
        f"{arabic.krippendorff_alpha_interval:.3f}"
        if arabic.krippendorff_alpha_interval is not None
        else "undefined/pending"
    )
    first_pass = (
        interval(autonomy.first_pass_approval_rate, True)
        if autonomy.first_pass_approval_rate
        else "pending"
    )
    kappa = (
        f"{brand.quadratic_weighted_kappa:.3f}"
        if brand.quadratic_weighted_kappa is not None
        else "pending human labels"
    )
    groups = "; ".join(
        f"{name}: {group.input_tokens / group.posts:.0f} in/"
        f"{group.output_tokens / group.posts:.0f} out tokens; "
        f"local p50/p95 {group.wall_p50_ms:.2f}/{group.wall_p95_ms:.2f} ms; "
        f"actual ${group.actual_spend_usd / group.posts:.4f}/post; paid "
        + (
            f"${group.mean_paid_list_price_usd.mean:.4f}/post"
            if group.mean_paid_list_price_usd
            else "pending"
        )
        for name, group in efficiency.groups.items()
    )
    timing = (
        interval(autonomy.human_minutes_per_week)
        if autonomy.human_minutes_per_week
        else "Pending human timing"
    )
    lines = [
        "| Metric | Result (95% interval where shown) | Evidence / limitation |",
        "|---|---|---|",
        f"| Brand consistency | {interval(brand.judge_mean)} / 5; "
        f"hard rules {interval(brand.hard_rule_pass_rate, True)} | Canned judge, κ {kappa}; "
        f"({brand.labeled_posts}/20 posts); control {interval(brand.negative_control_mean)} / 5 |",
        f"| Arabic quality | Human native: {human_arabic}; "
        f"MT: {human_mt}; native win: {human_win} | Canned judge "
        f"{interval(arabic.judge_mean)} / 5; {arabic.paired_posts}/20 human pairs; "
        f"interval alpha {alpha}; authored MT fixtures; no real-model quality claim |",
        f"| Optimization uplift | {interval(result.optimization_uplift.uplift, True)} | "
        "Synthetic Thompson vs fixed week-1; weeks 9-12; 20 paired seeds |",
        f"| Efficiency | {groups} | Fixture tokens/local timing; "
        f"{efficiency.render_jobs} video renders |",
        f"| Autonomy | {timing}; configured automation "
        f"{autonomy.configured_automation_share:.1%}; first-pass approval {first_pass} | "
        "Topology only; "
        "full pipeline measurement pending approval; bench never publishes |",
        "",
        "Policy comparison (synthetic audience; seed-cluster intervals):",
        "",
        "| Policy | Weeks 9-12 engagement rate | Cumulative expected regret | "
        "Leaked / learned posts |",
        "|---|---|---|---|",
    ]
    for policy, row in result.optimization_uplift.summaries.items():
        lines.append(
            f"| {policy} | {interval(row.late_engagement_rate, True)} | "
            f"{interval(row.cumulative_regret)} | {row.leaked_posts} / {row.learned_posts} |"
        )
    difference = result.optimization_uplift.leakage_guard_regret_difference
    lines.extend(
        [
            "",
            f"Synthetic D1-on minus D1-off regret: {interval(difference)}. "
            "Negative favors the guard; an interval crossing zero does not establish a difference.",
            "",
            "Generated from [bench/results.json](bench/results.json). "
            "[Protocol, rubric and HUMAN steps](bench/README.md). Canned rubric/control scores "
            "test the harness; they do not establish real judge accuracy.",
        ]
    )
    return "\n".join(lines)


def update_readme(path: Path, results_path: Path) -> None:
    """FR-14: replace only one explicit block; malformed markers fail before any write."""
    result = BenchmarkResults.model_validate_json(results_path.read_bytes())
    text = path.read_text(encoding="utf-8")
    if text.count(START) != 1 or text.count(END) != 1 or text.index(END) < text.index(START):
        raise ValueError("README requires one ordered benchmark marker pair")
    before, remaining = text.split(START)
    _, after = remaining.split(END)
    path.write_text(
        before + START + "\n" + render_table(result) + "\n" + END + after, encoding="utf-8"
    )
