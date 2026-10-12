"""NFR-07: offline smoke command; future-phase commands fail explicitly."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from instabay.adapters.fake_llm import FakeLLM
from instabay.core.fixture_schemas import CopyFixture
from instabay.db import SQLiteCallStore
from instabay.llm import LLMService

app = typer.Typer(no_args_is_help=True)


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
def demo() -> None:
    """FR-09: do not simulate an approval loop before Phase 2 is implemented."""
    _pending(2, "Weekly demo")


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
) -> None:
    """FR-10, FR-13: never call an external publisher from the Phase 1 scaffold."""
    _pending(3, "Multi-week cycle")
