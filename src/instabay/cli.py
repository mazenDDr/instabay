"""FR-09, NFR-07: offline week, explicit human approval and resumable dry-run exports."""

import os
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import yaml
from rich.console import Console

from instabay.adapters.fake_llm import FakeLLM
from instabay.approval import approval_queue, show_post
from instabay.core.fixture_schemas import CopyFixture
from instabay.core.schemas import BrandConstitution, BrandInput, WorkflowInput
from instabay.cycle import CycleInput, CycleRunner
from instabay.db import SQLiteCallStore
from instabay.graph import ApprovalPendingError, WeekRunner
from instabay.llm import LLMService
from instabay.repository import Repository
from instabay.settings import Settings

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
console = Console()
DEFAULT_DB = Path(os.environ.get("INSTABAY_DB_PATH", "outputs/demo.sqlite3"))
DEFAULT_CHECKPOINTS = Path(
    os.environ.get("INSTABAY_CHECKPOINTS_PATH", "outputs/demo-checkpoints.sqlite3")
)
DEFAULT_OUTBOX = Path(os.environ.get("INSTABAY_OUTBOX_PATH", "outbox/demo"))
DEFAULT_INPUTS = Path("config/brand_inputs.example.yaml")


def _brand_input(path: Path) -> BrandInput:
    return BrandInput.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _offline_only() -> None:
    if Settings.from_env().mode != "dry_run":
        raise typer.BadParameter("This phase only implements offline dry_run commands")


@app.command()
def smoke(
    db: Annotated[Path, typer.Option(help="SQLite call-ledger and cache path")] = Path(
        "outputs/instabay.sqlite3"
    ),
    fixtures: Annotated[Path, typer.Option(help="Local canned response directory")] = Path(
        "tests/fixtures/llm"
    ),
) -> None:
    """NFR-03, NFR-07: exercise fixture validation, persistent caching and usage logs."""
    fake = FakeLLM(fixtures)
    with SQLiteCallStore(db) as store:
        service = LLMService(fake, store)
        for template in ("copy_en", "copy_ar"):
            output = service.generate(
                template_name=template,
                slot_id="wk42-tue-1",
                inputs={"angle": "The quiet of the Red Sea in the morning"},
                output_type=CopyFixture,
            )
            typer.echo(output.caption)
        typer.echo(f"Phase 1 smoke passed. Provider calls: {fake.calls}; ledger: {db}")


def _pending(phase: int, feature: str) -> NoReturn:
    typer.echo(f"{feature} is not implemented yet; scheduled for Phase {phase}.", err=True)
    raise typer.Exit(2)


@app.command()
def demo(
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
    checkpoints: Annotated[Path, typer.Option()] = DEFAULT_CHECKPOINTS,
    outbox: Annotated[Path, typer.Option()] = DEFAULT_OUTBOX,
    brand_inputs: Annotated[Path, typer.Option()] = DEFAULT_INPUTS,
    run_id: Annotated[str, typer.Option()] = "2026-w42",
    week_start: Annotated[str, typer.Option()] = "2026-10-12",
) -> None:
    """FR-09: generate one fixture week and stop at a persistent approval interrupt."""
    _offline_only()
    request = WorkflowInput(run_id=run_id, week_start=date.fromisoformat(week_start))
    with WeekRunner(db, checkpoints, outbox, _brand_input(brand_inputs)) as runner:
        result = runner.start(request)
        typer.echo("Offline demo: unfrozen fixture brand; judge scores are illustrative.")
        typer.echo(f"Run {result.run_id}: {result.status}; {len(result.post_ids)} posts")
        if result.status == "approval_pending":
            for post_id in result.post_ids:
                show_post(runner.repository, post_id, console)
            typer.echo("STOPPED at human approval. No outbox artifacts were published.")
            typer.echo(f"Next: instabay approve --run-id {run_id} --actor YOUR_NAME")
            typer.echo(f"Then: instabay resume --run-id {run_id}")
        else:
            typer.echo(
                f"Already completed: {len(runner.repository.publications(run_id))} dry-run exports"
            )


@app.command()
def approve(
    actor: Annotated[str, typer.Option(help="Human making the decisions")],
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
    run_id: Annotated[str, typer.Option()] = "2026-w42",
    post_id: Annotated[str | None, typer.Option(help="Review just one post")] = None,
) -> None:
    """FR-09: ask for approve/edit/reject per post; persist elapsed seconds and edit diffs."""
    repository = Repository(db)
    try:
        repository.run(run_id)
        count = approval_queue(repository, run_id, actor, console, post_id)
        typer.echo(f"Stored {count} human decisions. Resume is a separate command.")
    finally:
        repository.close()


@app.command()
def resume(
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
    checkpoints: Annotated[Path, typer.Option()] = DEFAULT_CHECKPOINTS,
    outbox: Annotated[Path, typer.Option()] = DEFAULT_OUTBOX,
    brand_inputs: Annotated[Path, typer.Option()] = DEFAULT_INPUTS,
    run_id: Annotated[str, typer.Option()] = "2026-w42",
) -> None:
    """FR-09: resume only from stored approvals, across independent CLI processes."""
    _offline_only()
    with WeekRunner(db, checkpoints, outbox, _brand_input(brand_inputs)) as runner:
        try:
            result = runner.resume(run_id)
        except ApprovalPendingError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(2) from None
        typer.echo(
            f"Run {result.run_id}: {result.status}; "
            f"{len(runner.repository.publications(run_id))} dry-run exports to {outbox}"
        )


@app.command("brand-draft")
def brand_draft(
    output: Annotated[Path, typer.Option()] = Path("outputs/brand.draft.yaml"),
    inputs: Annotated[Path, typer.Option()] = DEFAULT_INPUTS,
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
) -> None:
    """FR-01: write an LLM draft to outputs, never edit or freeze config/brand.yaml."""
    from instabay.agents.brand_architect import BrandArchitect

    _offline_only()
    if output.resolve() == Path("config/brand.yaml").resolve():
        raise typer.BadParameter("config/brand.yaml is reserved for human editing")
    with SQLiteCallStore(db) as store:
        brand = BrandArchitect(LLMService(FakeLLM(Path("tests/fixtures/llm")), store)).draft(
            _brand_input(inputs)
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(brand.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    typer.echo(f"Draft only: {output}. # HUMAN: edit config/brand.yaml, then run brand-freeze.")


@app.command("brand-freeze")
def brand_freeze(
    actor: Annotated[str, typer.Option(help="Human freezing the constitution")],
    brand: Annotated[Path, typer.Option()] = Path("config/brand.yaml"),
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
) -> None:
    """FR-01: HUMAN-invoked command stores a hash of an existing human-edited file."""
    constitution = BrandConstitution.model_validate(
        yaml.safe_load(brand.read_text(encoding="utf-8"))
    )
    repository = Repository(db)
    try:
        digest = repository.register_brand(constitution, actor=actor)
        typer.echo(f"Stored human-frozen brand: {digest}")
    finally:
        repository.close()


@app.command()
def bench() -> None:
    """FR-14: do not report benchmark results before the benchmark phase."""
    _pending(4, "Benchmark harness")


@app.command()
def render(
    recipe: Annotated[Path, typer.Option()], backend: Annotated[str, typer.Option()] = "stub"
) -> None:
    """FR-06: video recipes and backends arrive in Phase 7."""
    _pending(7, "Video rendering")


@app.command()
def cycle(
    weeks: Annotated[int, typer.Option(min=1)] = 3,
    live: Annotated[bool, typer.Option()] = False,
    confirm_live: Annotated[bool, typer.Option()] = False,
    db: Annotated[Path, typer.Option()] = DEFAULT_DB,
    checkpoints: Annotated[Path, typer.Option()] = DEFAULT_CHECKPOINTS,
    outbox: Annotated[Path, typer.Option()] = DEFAULT_OUTBOX,
    brand_inputs: Annotated[Path, typer.Option()] = DEFAULT_INPUTS,
    fixtures: Annotated[Path, typer.Option()] = Path("tests/fixtures/llm"),
    cycle_id: Annotated[str, typer.Option()] = "cycle",
    seed: Annotated[int, typer.Option(min=0)] = 7,
    week_start: Annotated[str, typer.Option()] = "2026-10-12",
) -> None:
    """FR-09, FR-13: plan using sampled beliefs; every week stops for stored human decisions."""
    _offline_only()
    if live or confirm_live:
        raise typer.BadParameter("Live cycles are deferred until the Graph adapter phase")
    request = CycleInput(
        id=cycle_id, weeks=weeks, seed=seed, week_start=date.fromisoformat(week_start)
    )
    result = CycleRunner(db, checkpoints, outbox, _brand_input(brand_inputs), fixtures).run(request)
    typer.echo(
        "Synthetic cycle: canned EN/AR and D1 labels; no calibrated engine or real insights."
    )
    for report in result.reports:
        rate = f"{report.engagement_rate:.2%}" if report.engagement_rate is not None else "no data"
        typer.echo(
            f"{report.run_id}: {report.exported} exports; {report.learned} learned; "
            f"{report.leaked} leaked; {report.unverified} unverified; engagement {rate}"
        )
    typer.echo(
        f"Cycle {result.cycle_id}: {result.status}; {len(result.reports)}/{weeks} weeks complete"
    )
    if result.current_run_id:
        typer.echo(
            f"STOPPED for human approval. instabay approve --run-id {result.current_run_id} "
            f"--actor YOUR_NAME --db {db}"
        )
        typer.echo("Then rerun this same cycle command to export, learn and draft the next week.")
