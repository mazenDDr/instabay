"""FR-08: HUMAN-supplied labels fit offline; no model execution or label invention."""

from pathlib import Path
from typing import Annotated

import typer

from instabay.decisions.calibration import CalibrationData, fit_calibration


def register_decision_commands(app: typer.Typer) -> None:
    """FR-08: synthetic artifacts stay explicitly marked and cannot enable native fast paths."""

    @app.command("calibrate-decisions")
    def calibrate(
        data: Annotated[
            Path, typer.Option(help="HUMAN: recorded predictions and audited independent labels")
        ],
        output: Annotated[Path, typer.Option()] = Path("outputs/decisions/calibration.json"),
    ) -> None:
        """Fit grouped validation thresholds offline and report held-out per-language evidence."""
        try:
            dataset = CalibrationData.model_validate_json(data.read_bytes())
            profile = fit_calibration(dataset)
        except (ValueError, OSError):
            typer.echo(
                "Calibration stopped: supply recorded predictions and audited labels. "
                "See docs/DECISIONS.md.",
                err=True,
            )
            raise typer.Exit(2) from None
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(profile.model_dump_json(indent=2) + "\n")
        typer.echo(f"Wrote {output}; provenance={profile.provenance}; status={profile.status}")
        if profile.provenance == "synthetic":
            typer.echo("Synthetic evidence cannot enable a native decision engine.")
