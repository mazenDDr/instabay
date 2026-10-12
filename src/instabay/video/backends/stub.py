"""FR-06, NFR-07: deterministic Ken Burns over a still, no model or network."""

from pathlib import Path
from time import perf_counter

from instabay.video.backends.base import BackendCaps, ShotRecipe, ShotResult
from instabay.video.files import RenderError, binary, command, local_file


class StubVideoBackend:
    """NFR-05: visibly synthetic test route; no diffusion quality claim."""

    name = "stub"

    def capabilities(self) -> BackendCaps:
        """FR-06: only still motion, no synthesized FLF or audio."""
        return BackendCaps(resolutions=["recipe"], deterministic=True)

    def render_shot(self, shot: ShotRecipe, root: Path, directory: Path) -> ShotResult:
        """FR-06: bounded single-thread motion with fixed frame count."""
        started = perf_counter()
        recipe = shot.recipe
        item = recipe.shots.shots[shot.index]
        if item.end_keyframe or item.camera not in {
            "static",
            "push_in",
            "pull_out",
            "pan_left",
            "pan_right",
            "tilt_up",
            "tilt_down",
        }:
            raise RenderError("Stub does not support FLF or orbit")
        source = local_file(root, item.keyframe)
        spec = recipe.motion
        count = spec.frames[shot.index]
        progress = f"on/{max(1, count - 1)}"
        strength = item.motion_strength
        zoom = {
            "static": "1.0",
            "push_in": f"1+{strength}*{progress}",
            "pull_out": f"1+{strength}-{strength}*{progress}",
        }.get(item.camera, str(1 + strength))
        x, y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
        if item.camera in {"pan_left", "pan_right"}:
            x = f"(iw-iw/zoom)*{'1-' if item.camera == 'pan_left' else ''}{progress}"
        if item.camera in {"tilt_up", "tilt_down"}:
            y = f"(ih-ih/zoom)*{'1-' if item.camera == 'tilt_up' else ''}{progress}"
        output = directory / f"shot-{shot.index}.mp4"
        filters = (
            f"scale={spec.width}:{spec.height}:force_original_aspect_ratio=increase,"
            f"crop={spec.width}:{spec.height},"
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d={count}:"
            f"s={spec.width}x{spec.height}:fps={spec.fps},setsar=1"
        )
        command(
            [
                str(binary("ffmpeg")),
                "-v",
                "error",
                "-y",
                "-threads",
                "1",
                "-i",
                str(source),
                "-vf",
                filters,
                "-frames:v",
                str(count),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "1",
                str(output),
            ]
        )
        return ShotResult(file=str(output), seconds=perf_counter() - started)
