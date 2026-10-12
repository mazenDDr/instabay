"""FR-06: post-process explicitly recorded native motion without re-running the GPU."""

import json
from pathlib import Path

from instabay.core.schemas import canonical_hash
from instabay.video.backends.base import BackendCaps, ShotRecipe, ShotResult
from instabay.video.files import RenderError, local_file


class RecordedMotionBackend:
    """NFR-03: CPU import route; original model/runtime evidence remains in the recipe."""

    name = "stub"  # CPU render stage; recorded_motion.backend identifies generation.

    def capabilities(self) -> BackendCaps:
        """NFR-03: recorded bytes are deterministic inputs, not repeatable GPU inference."""
        return BackendCaps(resolutions=["recorded"], deterministic=True)

    def render_shot(self, shot: ShotRecipe, root: Path, directory: Path) -> ShotResult:
        """NFR-03: validate original recipe and crop identity before importing a clip."""
        recorded = shot.recipe.post.recorded_motion
        if recorded is None:
            raise RenderError("Recorded post needs stored motion provenance")
        native = json.loads(local_file(root, recorded.recipe).read_text())
        if canonical_hash(native) != recorded.recipe_hash or (
            native.get("spec", {}).get("image_sha256") != recorded.conditioning_sha256
            or native.get("ai_disclosure") is not True
            or native.get("reference_only") is not True
        ):
            raise RenderError("Recorded generation identity or conditioning differs")
        return ShotResult(file=str(local_file(root, recorded.clips[shot.index])), seconds=0)
