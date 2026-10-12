"""FR-06, FR-09: directed fractional-frame film reaches the existing approval interrupt."""

import shutil
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import WorkflowInput
from instabay.graph import ApprovalPendingError, WeekRunner
from instabay.video.backends.editorial import EditorialVideoBackend
from instabay.video.files import command, digest, probe
from instabay.video.post import editorial_overlay
from instabay.video.shotlist import SourceClip
from instabay.video.studio import VideoStudio
from tests.integration.test_week import inputs
from tests.unit.test_video_direction import ROOT, catalog


def test_directed_week_cfr_sound_and_approval_boundary(tmp_path: Path) -> None:
    # All inputs are local: no GPU, service, weights or credentials in the acceptance test.
    shutil.copytree(ROOT / "assets/fonts", tmp_path / "assets/fonts")
    shutil.copytree(ROOT / "assets/photos", tmp_path / "assets/photos")
    studio = VideoStudio(
        tmp_path / "state.sqlite", tmp_path, tmp_path / "renders", EditorialVideoBackend()
    )
    # Mix 12fps motion inputs and 30fps photo edits, the case that reset FFmpeg's frame counter.
    objects = catalog()
    for object_id, color in [("flowers", "red"), ("water", "green")]:
        clip = tmp_path / f"{object_id}.mp4"
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=576x1024:r=12:d=5.1",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-threads",
                "1",
                "-colorspace",
                "bt709",
                str(clip),
            ]
        )
        source = SourceClip(
            uri=clip.name, sha256=digest(clip), generated=False, credit="offline fixture"
        )
        objects = objects.model_copy(
            update={
                "objects": [
                    o.model_copy(update={"clip": source}) if o.id == object_id else o
                    for o in objects.objects
                ]
            }
        )
    out = tmp_path / "outbox"
    with WeekRunner(
        tmp_path / "state.sqlite",
        tmp_path / "checkpoints.sqlite",
        out,
        inputs(),
        video_studio=studio,
        video_catalog=objects,
    ) as runner:
        stopped = runner.start(WorkflowInput(run_id="2026-w42", week_start=date(2026, 10, 12)))
        assert stopped.status == "approval_pending" and not out.exists()
        post = runner.repository.post("2026-w42-sun-1")
        assert post.render_artifact and post.render_artifact.qa_status == "needs_review"
        assert "video_director" in post.prompt_hashes and "shot_list" not in post.prompt_hashes
        recipe = RenderRecipe.model_validate(post.render_artifact.render_recipe)
        assert recipe.post.style == "editorial" and recipe.post.language == "en"
        assert recipe.shots.audio.music and len(recipe.shots.shots) == 8
        assert all(s.end_keyframe is None for s in recipe.shots.shots)
        assert any(s.seconds != int(s.seconds) for s in recipe.shots.shots)
        video = next(
            s for s in probe(Path(post.media_path))["streams"] if s["codec_type"] == "video"
        )
        assert video["r_frame_rate"] == video["avg_frame_rate"] == "30/1"
        assert int(video["nb_frames"]) == 540 and float(video["duration"]) == 18
        samples = command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                post.media_path,
                "-vn",
                "-ac",
                "1",
                "-f",
                "s16le",
                "-",
            ]
        )
        assert any(samples)  # AAC track contains the actual score, not a silent placeholder.
        assert recipe.model.workflow
        assert (tmp_path / recipe.model.workflow.uri).exists()
        with pytest.raises(ApprovalPendingError):
            runner.resume("2026-w42")
        assert not out.exists()


def test_white_unboxed_arabic_has_transparent_safe_area(tmp_path: Path) -> None:
    out = tmp_path / "arabic.png"
    editorial_overlay(
        "ماذا لو تمهلنا؟",
        ROOT / "assets/fonts/NotoSansArabic.ttf",
        out,
        arabic=True,
        upper=False,
        credit=None,
    )
    with Image.open(out) as image:
        assert image.getpixel((100, 1400))[3] == 0
        assert image.getpixel((500, 300))[3] == 0
        pixels = list(image.get_flattened_data())
        opaque = [p for p in pixels if p[3] == 255]
        assert opaque and all(p[0] == p[1] == p[2] for p in opaque)
        assert sum(p[3] > 0 for p in pixels) / len(pixels) < 0.06
