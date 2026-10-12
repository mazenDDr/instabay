"""FR-06: users provide a brief and media catalog; the director owns the shot sequence."""

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from instabay.adapters.fake_llm import FakeLLM
from instabay.adapters.native_llm import NativeLLMClient
from instabay.agents.video_director import VideoDirector
from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import Brief, canonical_hash
from instabay.db import SQLiteCallStore
from instabay.llm import LLMOutputError, LLMService
from instabay.video.backends.editorial import EditorialVideoBackend
from instabay.video.creative_qa import creative_report
from instabay.video.direction import ObjectCatalog, VideoBoard, compile_board, resolve_object
from instabay.video.files import digest
from instabay.video.keyframes import stub_recipe
from instabay.video.music import ProceduralPreviewMusic
from instabay.video.studio import VideoStudio


def editorial_recipe(
    board: VideoBoard, root: Path, directory: Path, language: str, *, animatic: bool
) -> RenderRecipe:
    """NFR-03: brief, board, crops, clips, fonts and actual audio bytes precede rendering."""
    root, directory = root.resolve(), directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    board_file = directory / "boards" / f"{canonical_hash(board)}.json"
    board_file.parent.mkdir(parents=True, exist_ok=True)
    board_file.write_text(board.model_dump_json(indent=2) + "\n")
    shots = compile_board(board, root, directory / "references", animatic=animatic)
    shots = shots.model_copy(
        update={"audio": ProceduralPreviewMusic().score(board, root, directory)}
    )
    data = stub_recipe(shots, root).model_dump()
    data["motion"].update(width=576, height=1024)
    data["model"].update(
        repo="instabay/editorial-assembler",
        pipeline_class="EditorialVideoBackend",
        workflow={"uri": board_file.relative_to(root).as_posix(), "sha256": digest(board_file)},
    )
    used = [o for o in board.catalog.objects if o.id in {b.object_id for b in board.plan.beats}]
    authors = " / ".join(dict.fromkeys(o.author for o in used))
    licenses = " / ".join(dict.fromkeys(o.license_id for o in used))
    data["post"].update(
        style="editorial",
        language=language,
        frame_interpolation="motion"
        if board.plan.edit_style == "scenic" and not animatic
        else "repeat",
        font={
            "uri": "assets/fonts/NotoSansArabic.ttf",
            "sha256": digest(root / "assets/fonts/NotoSansArabic.ttf"),
        },
        latin_font={
            "uri": "assets/fonts/Manrope.ttf",
            "sha256": digest(root / "assets/fonts/Manrope.ttf"),
        },
        credit=f"Photos: {authors}\n{licenses} - cropped and animated",
    )
    return RenderRecipe.model_validate(data)


def register_direction_commands(app: typer.Typer) -> None:
    """FR-09: stage creative planning and previews; never approve a post."""

    @app.command("direct-video")
    def direct(
        brief: Annotated[Path, typer.Option()],
        catalog: Annotated[Path, typer.Option()] = Path("config/resort-objects.yaml"),
        output: Annotated[Path, typer.Option()] = Path("outputs/directed-resort"),
        reel_id: Annotated[str, typer.Option()] = "2026-w42-sun-1",
        model: Annotated[str | None, typer.Option()] = None,
        confirm_generation: Annotated[bool, typer.Option()] = False,
        origin: Annotated[str, typer.Option()] = "http://127.0.0.1:18765",
        board: Annotated[Path | None, typer.Option()] = None,
        render: Annotated[bool, typer.Option()] = False,
        animatic: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """FR-06: translate a semantic brief into a directed film without manual keyframes."""
        output = output.resolve()
        root = Path.cwd()
        if not output.is_relative_to(root):
            raise typer.BadParameter("Output must be under the recipe root")
        output.mkdir(parents=True, exist_ok=True)
        objects = ObjectCatalog.model_validate(yaml.safe_load(catalog.read_text()))
        shared = Brief.model_validate_json(brief.read_bytes())
        if board:
            bound = VideoBoard.model_validate_json(board.read_bytes())
            if bound.brief != shared:
                raise typer.BadParameter("Saved board belongs to another brief")
            old = bound.catalog.model_dump(exclude={"objects": {"__all__": {"clip"}}})
            new = objects.model_dump(exclude={"objects": {"__all__": {"clip"}}})
            if old != new:
                raise typer.BadParameter("Source catalog changed; direct a new board")
            bound = bound.model_copy(update={"catalog": objects})
        else:
            if model and not confirm_generation:
                raise typer.BadParameter("Native direction needs --confirm-generation")
            client = (
                NativeLLMClient(origin, model, confirm_external=True)
                if model
                else FakeLLM(Path("tests/fixtures/llm"))
            )
            try:
                with SQLiteCallStore(output / "director.sqlite") as store:
                    service = LLMService(
                        client, store, model_overrides={"video_director": model} if model else {}
                    )
                    try:
                        bound = VideoDirector(service).direct(reel_id, shared, objects)
                    except LLMOutputError:
                        if isinstance(client, NativeLLMClient) and client.last_completion:
                            (output / "director-invalid.json").write_text(
                                client.last_completion.output_json, encoding="utf-8"
                            )
                        raise
                    (output / "generation.json").write_text(
                        json.dumps(
                            {
                                "usage": service.usage.model_dump(),
                                "calls": [c.model_dump(mode="json") for c in store.calls()],
                                "synthetic": model is None,
                            },
                            indent=2,
                        )
                        + "\n"
                    )
            finally:
                if isinstance(client, NativeLLMClient):
                    client.close()
        (output / "board.json").write_text(bound.model_dump_json(indent=2) + "\n")
        requests = []
        for beat in bound.plan.beats:
            item = objects.get(beat.object_id)
            if beat.action != "photo_camera" and item.clip is None:
                key = resolve_object(item, root, output / "references")
                requests.append(
                    {
                        "beat_id": beat.id,
                        "object_id": item.id,
                        "reference": key.model_dump(mode="json"),
                        "action": beat.action,
                        "action_prompt": (
                            (
                                Path(__file__).parents[1] / "prompts" / f"motion_{beat.action}.md"
                            ).read_text()
                            + "\nObserved evidence: "
                            + item.observed
                        )
                        if beat.action in {"water_ripples", "plant_sway", "scenic_motion"}
                        else beat.action_prompt,
                        "needed_seconds": beat.frames / 30,
                    }
                )
        (output / "motion-requests.json").write_text(
            json.dumps(requests, ensure_ascii=False, indent=2) + "\n"
        )
        typer.echo(
            f"Directed board: {output / 'board.json'}; {len(requests)} missing motion clips."
        )
        if render:
            for language in ("en", "ar"):
                recipe = editorial_recipe(bound, root, output, language, animatic=animatic)
                result = VideoStudio(
                    output / "renders.sqlite", root, output / "renders", EditorialVideoBackend()
                ).render(recipe)
                label = "animatic" if animatic else "directed"
                (output / f"{label}-{language}.mp4").write_bytes(Path(result.file).read_bytes())
                (output / f"{label}-{language}-contact.jpg").write_bytes(
                    Path(result.contact_sheet).read_bytes()
                )
                (output / f"{label}-{language}-result.json").write_text(
                    result.model_dump_json(indent=2) + "\n"
                )
                report = creative_report(bound, recipe, root)
                (output / f"{label}-{language}-creative.json").write_text(
                    report.model_dump_json(indent=2) + "\n"
                )
                first = bound.plan.beats[0].overlay
                last = bound.plan.beats[-1].overlay
                caption = (
                    (first.en + "\n" + last.en) if language == "en" else (first.ar + "\n" + last.ar)
                )
                if result.ai_disclosure:
                    caption += (
                        "\nScenes created with AI."
                        if language == "en"
                        else "\nمشاهد تم إنشاؤها بالذكاء الاصطناعي."
                    )
                credits = [
                    {
                        "object_id": o.id,
                        "author": o.author,
                        "source": o.source_page,
                        "license": o.license_id,
                        "license_url": o.license_url,
                        "changes": "cropped, edited and animated",
                    }
                    for o in objects.objects
                    if o.id in {b.object_id for b in bound.plan.beats}
                ]
                (output / f"{label}-{language}-caption.json").write_text(
                    json.dumps(
                        {
                            "caption": caption,
                            "credits": credits,
                            "reference_only": result.reference_only,
                            "ai_disclosure": result.ai_disclosure,
                            "post_approved": False,
                            "brief_hash": bound.brief_hash,
                            "recipe_hash": result.recipe_hash,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
                typer.echo(
                    f"Saved {label}-{language}.mp4; preview only, not approved or published."
                )
