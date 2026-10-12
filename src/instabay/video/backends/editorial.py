"""FR-06: assemble authentic camera edits and individual motion clips chosen by the director."""

import json
from pathlib import Path

from instabay.core.schemas import canonical_hash
from instabay.video.backends.base import ShotRecipe, ShotResult
from instabay.video.backends.stub import StubVideoBackend
from instabay.video.files import RenderError, local_file, probe


class EditorialVideoBackend(StubVideoBackend):
    """NFR-03: CPU assembly; generated source provenance is retained per individual shot."""

    def render_shot(self, shot: ShotRecipe, root: Path, directory: Path) -> ShotResult:
        """FR-06: use real bytes or photograph motion, never quietly replace missing footage."""
        item = shot.recipe.shots.shots[shot.index]
        clip = item.source_clip
        if clip is None:
            return super().render_shot(shot, root, directory)
        source = local_file(root, clip)
        if float(probe(source)["format"]["duration"]) + 1 / 30 < item.seconds + clip.start_s:
            raise RenderError("Source footage cannot cover the directed shot")
        if clip.generated:
            if item.keyframe.source != "photo":
                raise RenderError("Synthetic evidence cannot authorize generated resort footage")
            if clip.motion_recipe is None:
                raise RenderError("Missing generated motion provenance")
            native = json.loads(local_file(root, clip.motion_recipe).read_text())
            if (
                canonical_hash(native) != clip.motion_recipe_hash
                or native.get("spec", {}).get("image_sha256") != item.keyframe.sha256
                or native.get("ai_disclosure") is not True
                or native.get("reference_only") is not True
            ):
                raise RenderError("Generated shot does not match its approved source object")
        return ShotResult(file=str(source), seconds=0)
