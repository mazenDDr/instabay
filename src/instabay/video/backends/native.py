"""NFR-03, NFR-04: explicit human-only GPU activation and pinned runtime checks."""

import os
import platform
from pathlib import Path

from instabay.core.recipe import RenderRecipe
from instabay.video.files import RenderError, digest, local_file


def require_gpu(confirm: bool) -> None:
    """NFR-04: HUMAN: run on gpu-box; no implicit inference from a laptop or test."""
    if (
        not confirm
        or os.environ.get("INSTABAY_VIDEO_ENABLED") != "1"
        or platform.system() != "Linux"
    ):
        raise RenderError("HUMAN: run on gpu-box with explicit GPU opt-in")


def checkpoint_directory(recipe: RenderRecipe, root: Path) -> Path:
    """NFR-03: all checkpoint/config bytes are pinned, including unlisted-file refusal."""
    uri = recipe.model.scheduler_config.get("local_model_uri")
    if not isinstance(uri, str):
        raise RenderError("Recipe needs a local_model_uri, not a remote model download")
    directory = (root / uri).resolve()
    if not directory.is_relative_to(root.resolve()) or not directory.is_dir():
        raise RenderError("Checkpoint must be inside the read-only input root")
    pinned = {local_file(root, ref).resolve(): ref.sha256 for ref in recipe.model.weights}
    actual = {p.resolve(): digest(p) for p in directory.rglob("*") if p.is_file()}
    if not actual or actual != pinned:
        raise RenderError("Entire checkpoint tree must match the recipe manifest")
    return directory
