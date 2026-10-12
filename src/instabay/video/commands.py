"""FR-06: explicit offline render and HUMAN-only native/golden commands."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import typer

from instabay.core.recipe import RenderRecipe
from instabay.video.backends.base import VideoBackend
from instabay.video.backends.comfyui import ComfyUIBackend
from instabay.video.backends.recorded import RecordedMotionBackend
from instabay.video.backends.stub import StubVideoBackend
from instabay.video.backends.wan_diffusers import WanDiffusersBackend
from instabay.video.files import RenderError
from instabay.video.keyframes import stub_recipe
from instabay.video.shotlist import ShotList
from instabay.video.studio import VideoStudio


def choose_backend(name: str, confirm_gpu: bool, flf: bool = False) -> VideoBackend:
    """NFR-05: optional native dependencies stay lazy; paid renders are not implemented."""
    if name == "stub":
        return StubVideoBackend()
    if name == "wan":
        return WanDiffusersBackend(confirm_gpu=confirm_gpu, flf_verified=flf)
    if name == "comfyui":
        return ComfyUIBackend(confirm_gpu=confirm_gpu, flf_verified=flf)
    raise ValueError("Supported backends: stub, wan, comfyui. HUMAN: Veo comparison is pending.")


def load_recipe(path: Path, backend: str, root: Path) -> RenderRecipe:
    """NFR-03: stub shot-list convenience captures measured identity before rendering."""
    data = json.loads(path.read_bytes())
    if backend == "stub" and "backend" not in data:
        return stub_recipe(ShotList.model_validate(data), root)
    recipe = RenderRecipe.model_validate(data)
    if recipe.backend != backend:
        raise ValueError("Backend argument differs from recipe")
    return recipe


def register_video_commands(app: typer.Typer) -> None:
    """FR-06: rendering never approves or publishes a post."""

    @app.command("render")
    def render(
        recipe: Annotated[Path, typer.Option()],
        backend: Annotated[str, typer.Option()] = "stub",
        root: Annotated[Path, typer.Option()] = Path("."),
        renders: Annotated[Path, typer.Option()] = Path("renders"),
        db: Annotated[Path, typer.Option()] = Path("outputs/render.sqlite3"),
        confirm_gpu: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """FR-07: produce a local preview, stored recipe, contact sheet and QA evidence."""
        adapter: VideoBackend | None = None
        try:
            request = load_recipe(recipe, backend, root)
            adapter = (
                RecordedMotionBackend()
                if request.post.recorded_motion
                else choose_backend(backend, confirm_gpu, request.model.supports_flf)
            )
            result = VideoStudio(db, root, renders, adapter).render(request)
            typer.echo(result.model_dump_json(indent=2, exclude={"frame_hashes"}))
            typer.echo(f"Decoded frame hashes: {len(result.frame_hashes)} (stored in result.json)")
            typer.echo("Preview only. Human approval and live media verification remain required.")
        except (RenderError, ValueError, OSError):
            typer.echo(
                "Render failed or inputs are invalid; native work requires HUMAN GPU opt-in.",
                err=True,
            )
            raise typer.Exit(2) from None
        finally:
            if isinstance(adapter, ComfyUIBackend):
                adapter.close()

    @app.command("golden")
    def golden(
        recipe: Annotated[Path, typer.Option()],
        backend: Annotated[str, typer.Option()] = "stub",
        root: Annotated[Path, typer.Option()] = Path("."),
        output: Annotated[Path, typer.Option()] = Path("outputs/golden.json"),
        confirm_gpu: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """NFR-03: render twice without cache reuse; compare every decoded frame."""
        request = load_recipe(recipe, backend, root)
        adapter = (
            RecordedMotionBackend()
            if request.post.recorded_motion
            else choose_backend(backend, confirm_gpu, request.model.supports_flf)
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with TemporaryDirectory(dir=output.parent) as work:
                directory = Path(work)
                first = VideoStudio(directory / "a.sqlite", root, directory / "a", adapter).render(
                    request
                )
                second = VideoStudio(directory / "b.sqlite", root, directory / "b", adapter).render(
                    request
                )
                match = first.frame_hashes == second.frame_hashes
                output.write_text(
                    json.dumps(
                        {
                            "recipe_hash": request.recipe_hash,
                            "backend": backend,
                            "frame_count": len(first.frame_hashes),
                            "decoded_frames_equal": match,
                            "first": first.frame_hashes,
                            "second": second.frame_hashes,
                            "scope": "same-runtime measured pair only; no cross-machine guarantee",
                        },
                        indent=2,
                    )
                    + "\n"
                )
                typer.echo(f"Decoded frames equal: {match}; evidence: {output}")
                if not match:
                    raise typer.Exit(1)
        finally:
            if isinstance(adapter, ComfyUIBackend):
                adapter.close()
