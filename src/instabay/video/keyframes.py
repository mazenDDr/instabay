"""FR-07: still resolution verifies bytes and approvals rather than inventing facilities."""

import importlib.metadata
import platform
import sys
from pathlib import Path

from instabay.core.recipe import ModelIdentity, MotionSpec, PostSpec, RenderRecipe, RuntimeIdentity
from instabay.core.schemas import canonical_hash
from instabay.video.files import binary, digest, local_file
from instabay.video.shotlist import FileRef, ShotList


def runtime_identity() -> RuntimeIdentity:
    """NFR-03: record tools, interpreter and implementation before any render."""
    package = Path(__file__).parents[1]
    sources: dict[str, object] = {
        str(p.relative_to(package)): digest(p) for p in sorted(package.rglob("*.py"))
    }
    return RuntimeIdentity(
        python=sys.version.split()[0],
        platform=platform.platform(),
        ffmpeg_sha256=digest(binary("ffmpeg")),
        ffprobe_sha256=digest(binary("ffprobe")),
        implementation_sha256=canonical_hash(sources),
        pillow=importlib.metadata.version("pillow"),
        reshaper=importlib.metadata.version("arabic-reshaper"),
        bidi=importlib.metadata.version("python-bidi"),
    )


def verify_inputs(recipe: RenderRecipe, root: Path) -> None:
    """NFR-03: every dependency is verified, including fonts, LUT and workflow."""
    refs: list[FileRef] = [s.keyframe for s in recipe.shots.shots] + [recipe.post.font]
    refs.extend(recipe.model.weights + recipe.model.loras)
    refs.extend(
        r
        for r in [
            recipe.post.lut,
            recipe.model.workflow,
            recipe.shots.audio.music,
            recipe.shots.audio.voiceover,
        ]
        if r is not None
    )
    for ref in refs:
        local_file(root, ref)


def stub_recipe(shots: ShotList, root: Path, *, preset: str = "fast") -> RenderRecipe:
    """NFR-07: build an exact CPU recipe; no photo crop is approved implicitly."""
    font = root / "assets/fonts/NotoNaskhArabic.ttf"
    return RenderRecipe(
        backend="stub",
        shots=shots,
        model=ModelIdentity(
            repo="instabay/stub-kenburns",
            revision="0" * 40,
            pipeline_class="StubVideoBackend",
            scheduler="frame-index",
        ),
        motion=MotionSpec(
            frames=[s.seconds * 30 for s in shots.shots], seeds=[7] * len(shots.shots)
        ),
        post=PostSpec.model_validate(
            {
                "font": {"uri": "assets/fonts/NotoNaskhArabic.ttf", "sha256": digest(font)},
                "preset": preset,
            }
        ),
        runtime=runtime_identity(),
    )
