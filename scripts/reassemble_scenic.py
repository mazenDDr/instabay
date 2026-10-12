"""FR-06, NFR-03: reassemble recorded scenic footage without recompressing conditioning."""

import argparse
from pathlib import Path

from instabay.core.recipe import RenderRecipe
from instabay.video.backends.editorial import EditorialVideoBackend
from instabay.video.keyframes import runtime_identity, verify_inputs
from instabay.video.studio import VideoStudio


def reassemble(recipe_file: Path, root: Path, output: Path) -> None:
    """NFR-03: retain immutable inputs; explicitly create a new CPU-runtime recipe/hash."""
    original = RenderRecipe.model_validate_json(recipe_file.read_bytes())
    if original.post.style != "editorial" or not all(
        shot.source_clip for shot in original.shots.shots
    ):
        raise ValueError("This replay requires an editorial recipe with recorded source clips")
    verify_inputs(original, root)
    recipe = RenderRecipe.model_validate(
        original.model_copy(update={"runtime": runtime_identity()}).model_dump()
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "recipe.json").write_text(recipe.model_dump_json(indent=2) + "\n")
    result = VideoStudio(
        output / "replay.sqlite", root, output / "renders", EditorialVideoBackend()
    ).render(recipe)
    print(result.model_dump_json(indent=2, exclude={"frame_hashes"}))
    print("Reference preview only; no approval or publication.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("outputs/coastal-replay"))
    args = parser.parse_args()
    reassemble(args.recipe, args.root.resolve(), args.output.resolve())
