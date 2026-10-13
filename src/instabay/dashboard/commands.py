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
    make_shot,
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
        generate: Annotated[
            bool, typer.Option(help="Enable the Generate week button (gpu-box caption model)")
        ] = False,
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

        pipeline = None
        if generate:
            import os

            from instabay.adapters.native_llm import NativeLLMClient
            from instabay.dashboard.jobs import WRITER_MODEL, Pipeline, SSHVisionService

            if os.environ.get("INSTABAY_LLM_ENABLED") != "1":
                raise typer.BadParameter("--generate needs INSTABAY_LLM_ENABLED=1")
            pipeline = Pipeline(
                root=Path.cwd().resolve(),
                runs=runs.resolve(),
                workspace=workspace.resolve(),
                brand=load_brand(brand),
                service=SSHVisionService(),
                engine=decider,
                judge=pillar_judge(judge, vision_origin, confirm_external),
                views=backend,
                view_revision=VIEW_REVISION,
                client_factory=lambda origin: NativeLLMClient(
                    origin, WRITER_MODEL, confirm_external=True
                ),
            )

        def retry(library: AssetLibrary, old: Asset) -> Asset:
            """FR-06: same sources and direction, next seed; the old attempt is kept."""
            assert backend is not None and old.recipe is not None
            seed = int(str(old.recipe.get("seed", 0))) + 1
            parents = [library.get(str(i)) for i in old.recipe.get("parents") or [old.parent_id]]  # type: ignore[union-attr]
            preset = str(old.recipe.get("preset", ""))
            if old.recipe.get("kind") == "new-shot-v1":
                _, pillar, variant = [*preset.split(":"), "", "", "0"][:3]
                return make_shot(
                    library,
                    parents,
                    pillar or str(old.pillar),
                    int(variant or 0),
                    seed,
                    backend=backend,
                    revision=VIEW_REVISION,
                    judge=decider,
                )
            return make_view(
                library,
                parents[0],
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
            shots=retry if backend else None,
            presets={k: v[0] for k, v in PRESETS.items()},
            pipeline=pipeline,
        )
        typer.echo(f"Dashboard: http://127.0.0.1:{port}  (loopback only; Ctrl+C to stop)")
        uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")
