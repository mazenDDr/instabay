"""FR-04: `instabay dashboard` serves the owner page on loopback only."""

from pathlib import Path
from typing import Annotated

import typer

from instabay.assets.commands import (
    VIEW_REVISION,
    VISION_ORIGIN,
    WORKSPACE,
    BrandFile,
    Workspace,
    load_brand,
    pillar_judge,
    vision_engine,
)
from instabay.assets.library import Asset, AssetLibrary
from instabay.assets.variants import (
    PRESETS,
    HTTPViewBackend,
    StubViewBackend,
    ViewBackend,
    make_view,
)


def register_dashboard_commands(app: typer.Typer) -> None:
    @app.command("dashboard")
    def dashboard(
        brand: BrandFile,
        workspace: Workspace = WORKSPACE,
        runs: Annotated[Path, typer.Option()] = Path("outputs"),
        port: Annotated[int, typer.Option(min=1024, max=65535)] = 8780,
        engine: Annotated[str, typer.Option(help="none, fake or d3")] = "none",
        fixtures: Annotated[Path, typer.Option()] = Path("tests/fixtures/vision"),
        vision_origin: Annotated[str, typer.Option()] = VISION_ORIGIN,
        confirm_external: Annotated[bool, typer.Option()] = False,
        views: Annotated[str, typer.Option(help="none, stub or gpu")] = "none",
        confirm_gpu: Annotated[bool, typer.Option()] = False,
        judge: Annotated[str, typer.Option(help="none or vlm")] = "none",
    ) -> None:
        """FR-02, FR-04: photos, weekly mix, plan and results at http://127.0.0.1:PORT."""
        import uvicorn

        from instabay.dashboard.app import create_app

        decider = (
            None
            if engine == "none"
            else vision_engine(engine, fixtures, vision_origin, confirm_external)
        )
        backend: ViewBackend | None = None
        if views == "stub":
            backend = StubViewBackend()
        elif views == "gpu":
            backend = HTTPViewBackend(vision_origin, confirm_gpu=confirm_gpu)
        elif views != "none":
            raise typer.BadParameter("Views must be none, stub or gpu")

        def render(library: AssetLibrary, parent: Asset, preset: str, seed: int) -> Asset:
            assert backend is not None
            return make_view(
                library,
                parent,
                preset,
                seed,
                backend=backend,
                revision=VIEW_REVISION,
                judge=decider,
            )

        application = create_app(
            workspace=workspace,
            brand=load_brand(brand),
            runs=runs,
            engine=decider,
            judge=pillar_judge(judge, vision_origin, confirm_external),
            variants=render if backend else None,
            presets={k: v[0] for k, v in PRESETS.items()},
        )
        typer.echo(f"Dashboard: http://127.0.0.1:{port}  (loopback only; Ctrl+C to stop)")
        uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")
