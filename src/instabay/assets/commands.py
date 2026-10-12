"""FR-04: `instabay assets ...` for owners who prefer the terminal to the dashboard."""

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
import yaml

from instabay.assets.classify import agreement, classify_assets
from instabay.assets.export import export_library
from instabay.assets.judge import HTTPPillarJudge, PillarJudge
from instabay.assets.library import AssetLibrary
from instabay.assets.plan import OwnerCadence, load_cadence, save_cadence, suggest_assets
from instabay.core.planner import plan_week
from instabay.core.schemas import BrandConstitution, canonical_hash
from instabay.decisions.jev_http import SystemOneConfig
from instabay.decisions.vision import (
    D3_FLASH,
    D3FlashHTTPEngine,
    FakeVisionEngine,
    VisionDecisionEngine,
)

WORKSPACE = Path("data/workspace")
VISION_ORIGIN = "http://127.0.0.1:18790"
D3_REVISION = "main"  # HUMAN: pin the downloaded commit hash once d3-flash is verified on gpu-box.
VIEW_REVISION = "main"  # HUMAN: pin the FLUX.2-klein-4B commit once measured on gpu-box.

Workspace = Annotated[Path, typer.Option(help="Asset library folder under the project root")]
BrandFile = Annotated[Path, typer.Option(help="Frozen brand constitution YAML")]


def load_brand(path: Path) -> BrandConstitution:
    return BrandConstitution.model_validate(yaml.safe_load(path.read_text()))


def vision_engine(
    engine: str, fixtures: Path, origin: str, confirm_external: bool
) -> VisionDecisionEngine:
    """FR-08: the fake engine is the default; d3-flash needs explicit opt-in and env flag."""
    if engine == "fake":
        return FakeVisionEngine.from_dir(fixtures)
    if engine != "d3":
        raise typer.BadParameter("Engine must be fake or d3")
    config = SystemOneConfig(base_url=origin, revision=D3_REVISION, model=D3_FLASH, timeout_s=60)
    return D3FlashHTTPEngine(config, confirm_external=confirm_external)


def pillar_judge(judge: str, origin: str, confirm_external: bool) -> PillarJudge | None:
    """FR-08: optional VLM second opinion for photos d3-flash is unsure about."""
    if judge == "none":
        return None
    if judge != "vlm":
        raise typer.BadParameter("Judge must be none or vlm")
    return HTTPPillarJudge(origin, confirm_external=confirm_external)


def register_asset_commands(app: typer.Typer) -> None:
    """FR-04: add, classify, review, plan and export the owner's photo library."""
    assets = typer.Typer(help="Brand owner photo library", no_args_is_help=True)
    app.add_typer(assets, name="assets")
    register_view_commands(assets)

    @assets.command("add")
    def add(
        photos: list[Path],
        added_by: Annotated[str, typer.Option("--by")],
        rights_confirmed: Annotated[bool, typer.Option()] = False,
        note_en: Annotated[str, typer.Option()] = "",
        note_ar: Annotated[str, typer.Option()] = "",
        workspace: Workspace = WORKSPACE,
    ) -> None:
        """FR-04: copy photos into the library; identical bytes are stored once."""
        with AssetLibrary(workspace) as library:
            for photo in photos:
                asset = library.add(
                    photo.read_bytes(),
                    added_by=added_by,
                    rights_confirmed=rights_confirmed,
                    note_en=note_en,
                    note_ar=note_ar,
                )
                typer.echo(f"{asset.id}\t{photo.name}\t{asset.width}x{asset.height}")

    @assets.command("classify")
    def classify(
        brand: BrandFile,
        workspace: Workspace = WORKSPACE,
        engine: Annotated[str, typer.Option()] = "fake",
        fixtures: Annotated[Path, typer.Option()] = Path("tests/fixtures/vision"),
        origin: Annotated[str, typer.Option()] = VISION_ORIGIN,
        confirm_external: Annotated[bool, typer.Option()] = False,
        force: Annotated[bool, typer.Option()] = False,
        judge: Annotated[str, typer.Option(help="none or vlm (Qwen3.5-9B on gpu-box)")] = "none",
    ) -> None:
        """FR-08: sort photos into pillars with d3-flash; unsure ones go to the VLM judge."""
        decider = vision_engine(engine, fixtures, origin, confirm_external)
        second = pillar_judge(judge, origin, confirm_external)
        with AssetLibrary(workspace) as library:
            report = classify_assets(library, decider, load_brand(brand), force=force, judge=second)
            assets = library.all()
        typer.echo(report.model_dump_json())
        typer.echo(f"d3 vs owner labels: {agreement(assets).model_dump_json()}")
        typer.echo(f"VLM vs owner labels: {agreement(assets, 'vlm').model_dump_json()}")

    @assets.command("review")
    def review(
        asset_id: str,
        pillar: Annotated[str | None, typer.Option()] = None,
        note_en: Annotated[str | None, typer.Option()] = None,
        note_ar: Annotated[str | None, typer.Option()] = None,
        approve: Annotated[bool | None, typer.Option("--approve/--unapprove")] = None,
        reject: Annotated[bool | None, typer.Option("--reject/--restore")] = None,
        workspace: Workspace = WORKSPACE,
    ) -> None:
        """FR-09: owner pillar label, bilingual description and approval of generated views."""
        with AssetLibrary(workspace) as library:
            asset = library.review(
                asset_id,
                owner_pillar=pillar,
                note_en=note_en,
                note_ar=note_ar,
                approved=approve,
                rejected=reject,
            )
        typer.echo(asset.model_dump_json(exclude={"recipe", "fidelity"}))

    @assets.command("list")
    def list_assets(workspace: Workspace = WORKSPACE) -> None:
        with AssetLibrary(workspace) as library:
            for a in library.all():
                state = "ready" if a.usable and a.described else "needs review"
                typer.echo(f"{a.id}\t{a.origin}\t{a.pillar or '-'}\t{state}\t{a.file}")

    @assets.command("cadence")
    def cadence(
        brand: BrandFile,
        posts: Annotated[int | None, typer.Option()] = None,
        reels: Annotated[int | None, typer.Option()] = None,
        carousels: Annotated[int | None, typer.Option()] = None,
        workspace: Workspace = WORKSPACE,
    ) -> None:
        """FR-02: show or change the weekly reels/carousels/photos mix."""
        constitution = load_brand(brand)
        with AssetLibrary(workspace) as library:
            current = load_cadence(library, constitution)
            if posts is not None or reels is not None or carousels is not None:
                current = OwnerCadence(
                    posts_per_week=posts if posts is not None else current.posts_per_week,
                    reels_per_week=reels if reels is not None else current.reels_per_week,
                    carousels_per_week=(
                        carousels if carousels is not None else current.carousels_per_week
                    ),
                )
                save_cadence(library, constitution, current)
        typer.echo(
            f"{current.posts_per_week} posts/week: {current.reels_per_week} reels, "
            f"{current.carousels_per_week} carousels, {current.photos_per_week} photos"
        )

    @assets.command("plan")
    def plan(
        brand: BrandFile,
        week_start: Annotated[str, typer.Option()],
        workspace: Workspace = WORKSPACE,
    ) -> None:
        """FR-02, FR-04: preview the week's slots with suggested photos; nothing is generated."""
        constitution = load_brand(brand)
        with AssetLibrary(workspace) as library:
            rhythm = load_cadence(library, constitution).cadence(constitution)
            slots = plan_week(
                constitution,
                canonical_hash(constitution),
                "preview",
                date.fromisoformat(week_start),
                cadence=rhythm,
            )
            suggestions = suggest_assets(slots, library.all())
        for slot in slots:
            s = suggestions[slot.id]
            flag = " (short)" if s.shortfall else ""
            typer.echo(
                f"{slot.scheduled_at:%a %H:%M}\t{s.format}\t{s.pillar}\t"
                f"{', '.join(s.primary) or '-'}{flag}"
            )

    @assets.command("export")
    def export(
        brand: BrandFile,
        workspace: Workspace = WORKSPACE,
    ) -> None:
        """FR-04: write evidence.yaml + objects.yaml for `instabay generate --assets`."""
        with AssetLibrary(workspace) as library:
            _, catalog = export_library(library, load_brand(brand), workspace / "export")
        typer.echo(f"{len(catalog.objects)} photos exported: {workspace / 'export'}")


def register_view_commands(assets: typer.Typer) -> None:
    """FR-06: batch camera views, then batch d3 checks (one model swap instead of many)."""
    from instabay.assets.variants import (
        PRESETS,
        HTTPViewBackend,
        StubViewBackend,
        ViewBackend,
        check_fidelity,
        make_view,
    )

    @assets.command("views")
    def views(
        asset_ids: list[str],
        preset: Annotated[list[str] | None, typer.Option(help="Repeat; default all")] = None,
        seed: Annotated[int, typer.Option(min=0)] = 0,
        backend: Annotated[str, typer.Option(help="stub or gpu")] = "stub",
        origin: Annotated[str, typer.Option()] = VISION_ORIGIN,
        confirm_gpu: Annotated[bool, typer.Option()] = False,
        workspace: Workspace = WORKSPACE,
    ) -> None:
        """FR-06: new camera views of owner photos; each waits for owner approval."""
        renderer: ViewBackend = (
            StubViewBackend()
            if backend == "stub"
            else HTTPViewBackend(origin, confirm_gpu=confirm_gpu)
        )
        with AssetLibrary(workspace) as library:
            for asset_id in asset_ids:
                for name in preset or list(PRESETS):
                    view = make_view(
                        library,
                        library.get(asset_id),
                        name,
                        seed,
                        backend=renderer,
                        revision=VIEW_REVISION,
                    )
                    typer.echo(f"{view.id}\t{asset_id}\t{name}\t{view.width}x{view.height}")

    @assets.command("check-views")
    def check_views(
        workspace: Workspace = WORKSPACE,
        engine: Annotated[str, typer.Option()] = "fake",
        fixtures: Annotated[Path, typer.Option()] = Path("tests/fixtures/vision"),
        origin: Annotated[str, typer.Option()] = VISION_ORIGIN,
        confirm_external: Annotated[bool, typer.Option()] = False,
        force: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """Rule 6: d3-flash same-place/photoreal scores for generated views."""
        judge = vision_engine(engine, fixtures, origin, confirm_external)
        with AssetLibrary(workspace) as library:
            for view in library.all():
                if view.origin != "generated" or (view.fidelity and not force):
                    continue
                checked = check_fidelity(library, view, judge)
                typer.echo(f"{checked.id}\t{json.dumps(checked.fidelity)}")
