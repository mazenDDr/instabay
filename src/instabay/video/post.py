"""FR-07, NFR-08: CPU post-processing with shaped Arabic and conservative reel encoding."""

import importlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from instabay.core.recipe import RenderRecipe
from instabay.video.files import RenderError, binary, command, local_file
from instabay.video.shotlist import Overlay


def shape_arabic(text: str) -> str:
    """NFR-08: reshape once, then reorder for a renderer without RTL shaping."""
    reshaped: str = importlib.import_module("arabic_reshaper").reshape(text)
    visual: str = importlib.import_module("bidi.algorithm").get_display(reshaped)
    return visual


def overlay_image(
    overlay: Overlay,
    font_path: Path,
    output: Path,
    *,
    synthetic: bool,
    preview_label: str | None = None,
    credit: str | None = None,
) -> None:
    """NFR-08: fit complete lines into a safe area; never clip or synthesize lettering."""
    image = Image.new("RGBA", (1080, 1920))
    draw = ImageDraw.Draw(image)
    blocks = [(overlay.en, False, 1420), (overlay.ar, True, 1580)]
    if synthetic:
        blocks.append(("SYNTHETIC OFFLINE DEMO", False, 210))
    for text, arabic, y in blocks:
        if not text:
            continue
        chosen: tuple[list[str], ImageFont.FreeTypeFont] | None = None
        for size in (60, 52, 44, 36, 30):
            font = ImageFont.truetype(str(font_path), size, layout_engine=ImageFont.Layout.BASIC)
            lines: list[str] = []
            line = ""
            for word in text.split():
                candidate = (line + " " + word).strip()
                visual = shape_arabic(candidate) if arabic else candidate
                if draw.textlength(visual, font=font) > 880 and line:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
            if len(lines) <= 2 and all(
                draw.textlength(shape_arabic(s) if arabic else s, font=font) <= 880 for s in lines
            ):
                chosen = (lines, font)
                break
        if chosen is None:
            raise RenderError("Overlay cannot fit inside the safe area")
        lines, font = chosen
        draw.rounded_rectangle(
            (60, y - 25, 1020, y + len(lines) * 82 + 10), radius=18, fill=(0, 20, 30, 190)
        )
        for index, line in enumerate(lines):
            draw.text(
                (540, y + index * 82),
                shape_arabic(line) if arabic else line,
                font=font,
                fill="white",
                anchor="mt",
                stroke_width=1,
            )
    for badge, y in ((preview_label, 190), (credit, 1790)):
        if badge:
            font = ImageFont.truetype(str(font_path), 28, layout_engine=ImageFont.Layout.BASIC)
            if draw.textlength(badge, font=font) > 960:
                raise RenderError("Preview credit or label exceeds its safe area")
            draw.rounded_rectangle((40, y - 18, 1040, y + 60), radius=12, fill=(0, 20, 30, 200))
            draw.text((540, y), badge, font=font, fill="white", anchor="mt")
    image.save(output)


def post_process(recipe: RenderRecipe, root: Path, files: list[Path], directory: Path) -> Path:
    """FR-07: deterministic CPU resampling, overlays, optional LUT/grain and audio mix."""
    font = local_file(root, recipe.post.font)
    lut = local_file(root, recipe.post.lut) if recipe.post.lut else None
    if lut:
        (directory / "brand.cube").write_bytes(lut.read_bytes())
    sequence = []
    for index, (shot, file) in enumerate(zip(recipe.shots.shots, files, strict=True)):
        overlay = directory / f"overlay-{index}.png"
        overlay_image(
            shot.overlay,
            font,
            overlay,
            synthetic=shot.keyframe.source == "synthetic",
            preview_label=recipe.post.preview_label,
            credit=recipe.post.credit,
        )
        output = directory / f"post-{index}.mp4"
        filters = (
            "scale=1080:1920:force_original_aspect_ratio=increase:out_range=tv,"
            "crop=1080:1920,fps=30,setsar=1,setparams=range=limited"
        )
        if lut:
            filters += ",lut3d=brand.cube"
        if recipe.post.grain_strength:
            filters += (
                f",noise=alls={recipe.post.grain_strength}:allf=t:"
                f"all_seed={recipe.motion.seeds[index]}"
            )
        graph = f"[0:v]{filters}[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        command(
            [
                str(binary("ffmpeg")),
                "-v",
                "error",
                "-y",
                "-threads",
                "1",
                "-i",
                str(file),
                "-loop",
                "1",
                "-i",
                str(overlay),
                "-filter_complex_threads",
                "1",
                "-filter_complex",
                graph,
                "-map",
                "[v]",
                "-t",
                str(shot.seconds),
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-preset",
                recipe.post.preset,
                "-crf",
                str(recipe.post.crf),
                "-threads",
                "1",
                "-fflags",
                "+bitexact",
                "-flags:v",
                "+bitexact",
                str(output),
            ],
            cwd=directory,
        )
        sequence.append(f"file 'post-{index}.mp4'")
    # Names are fixed and relative; user paths/text never enter concat syntax or filter expressions.
    concat = directory / "concat.txt"
    concat.write_text("\n".join(sequence) + "\n")
    output = directory / "reel.mp4"
    args = [
        str(binary("ffmpeg")),
        "-v",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "1",
        "-i",
        str(concat),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
    ]
    tracks = [r for r in [recipe.shots.audio.music, recipe.shots.audio.voiceover] if r]
    for track in tracks:
        args += ["-i", str(local_file(root, track))]
    if tracks:
        inputs = "".join(f"[{i}:a]" for i in range(1, 2 + len(tracks)))
        args += [
            "-filter_complex",
            f"{inputs}amix=inputs={1 + len(tracks)}:duration=longest[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
        ]
    else:
        args += ["-map", "0:v:0", "-map", "1:a:0"]
    args += [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-b:a",
        "128k",
        "-t",
        str(recipe.shots.duration_s),
        "-movflags",
        "+faststart",
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-map_metadata",
        "-1",
        str(output),
    ]
    command(args)
    return output


def contact_sheet(video: Path, directory: Path, duration: int) -> Path:
    """FR-09: one frame per second for human review beside the MP4."""
    output = directory / "contact-sheet.jpg"
    rows = (duration + 4) // 5
    command(
        [
            str(binary("ffmpeg")),
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps=1,scale=180:320,tile=5x{rows}",
            "-frames:v",
            "1",
            str(output),
        ]
    )
    return output
