"""FR-07, NFR-08: CPU post-processing with shaped Arabic and conservative reel encoding."""

import importlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from instabay.core.recipe import RenderRecipe
from instabay.video.files import RenderError, binary, command, local_file
from instabay.video.shotlist import Overlay


def editorial_overlay(
    text: str,
    font_path: Path,
    output: Path,
    *,
    arabic: bool,
    upper: bool,
    credit: str | None,
) -> None:
    """NFR-08: single-language thought, unboxed type, negative space and a small closing credit."""
    image = Image.new("RGBA", (1080, 1920))
    draw = ImageDraw.Draw(image)

    def font_at(size: int) -> ImageFont.FreeTypeFont:
        font = ImageFont.truetype(str(font_path), size, layout_engine=ImageFont.Layout.BASIC)
        try:
            axes = font.get_variation_axes()
            font.set_variation_by_axes(
                [
                    float(min(axis["maximum"] or 900, max(axis["minimum"] or 100, 700)))
                    if axis["name"] == b"Weight"
                    else float(axis["default"] or 100)
                    for axis in axes
                ]
            )
        except OSError:
            pass  # Static fonts have no variation axes.
        return font

    if text:
        lines: list[str] = []
        for size in (104, 92, 80, 68):
            font = font_at(size)
            lines = []
            line = ""
            for word in text.split():
                candidate = (line + " " + word).strip()
                visual = shape_arabic(candidate) if arabic else candidate
                if draw.textlength(visual, font=font) > 850 and line:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
            if len(lines) <= 2:
                break
        if len(lines) > 2 or any(
            draw.textlength(shape_arabic(t) if arabic else t, font=font) > 850 for t in lines
        ):
            raise RenderError("Directed text cannot fit its safe area")
        y = 420 if upper else 1320
        for index, line in enumerate(lines):
            draw.text(
                (540, y + index * 128),
                shape_arabic(line) if arabic else line,
                font=font,
                anchor="mt",
                fill="white",
                stroke_width=3,
                stroke_fill=(0, 0, 0, 140),
            )
    if credit:
        font = font_at(22)
        for index, line in enumerate(credit.split("\n")):
            if draw.textlength(line, font=font) > 900:
                raise RenderError("Closing credit cannot fit its safe area")
            draw.text(
                (540, 1720 + index * 38),
                line,
                font=font,
                anchor="mt",
                fill="white",
                stroke_width=1,
                stroke_fill=(0, 0, 0, 200),
            )
    image.save(output)


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
        if recipe.post.style == "editorial":
            text = shot.overlay.en if recipe.post.language == "en" else shot.overlay.ar
            text_font = (
                local_file(root, recipe.post.latin_font)
                if recipe.post.language == "en" and recipe.post.latin_font
                else font
            )
            editorial_overlay(
                text,
                text_font,
                overlay,
                arabic=recipe.post.language == "ar",
                upper=shot.text_position == "upper",
                credit=recipe.post.credit if shot.role == "cta" else None,
            )
        else:
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
        if recipe.post.style == "editorial":
            # Resampled 12fps footage can lose its last frame at a fractional cut.
            # Pad only the tail, then trim to the deterministic editor's exact frame count.
            filters += (
                f",tpad=stop_mode=clone:stop_duration=0.1,"
                f"trim=end_frame={round(shot.seconds * 30)},setpts=N/(30*TB)"
            )
        if lut:
            filters += ",lut3d=brand.cube"
        if recipe.post.grain_strength:
            filters += (
                f",noise=alls={recipe.post.grain_strength}:allf=t:"
                f"all_seed={recipe.motion.seeds[index]}"
            )
        if recipe.post.style == "editorial" and (shot.overlay.en or shot.overlay.ar):
            end = shot.text_end_s if shot.text_end_s is not None else shot.seconds
            fade = 0.1
            text_filter = (
                f"format=rgba,fade=t=in:st={shot.text_start_s}:d={fade}:alpha=1,"
                f"fade=t=out:st={end - fade}:d={fade}:alpha=1"
            )
            graph = (
                f"[0:v]{filters}[base];[1:v]{text_filter}[text];"
                "[base][text]overlay=0:0:format=auto,format=yuv420p[v]"
            )
        else:
            graph = f"[0:v]{filters}[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        command(
            [
                str(binary("ffmpeg")),
                "-v",
                "error",
                "-y",
                "-threads",
                "1",
                "-ss",
                str(shot.source_clip.start_s if shot.source_clip else 0),
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
                *(
                    ["-r", "30", "-fps_mode", "cfr", "-frames:v", str(round(shot.seconds * 30))]
                    if recipe.post.style == "editorial"
                    else ["-t", str(shot.seconds)]
                ),
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
        "-reinit_filter",
        "0",
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
            f"{inputs}amix=inputs={1 + len(tracks)}:duration=longest:normalize=0,"
            "alimiter=limit=0.95[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
        ]
    else:
        args += ["-map", "0:v:0", "-map", "1:a:0"]
    if recipe.post.style == "editorial":
        args += [
            "-vf",
            f"fps=30,tpad=stop_mode=clone:stop_duration=1,"
            f"trim=end_frame={recipe.shots.duration_s * 30},setpts=N/(30*TB)",
            "-r",
            "30",
            "-fps_mode",
            "cfr",
            "-frames:v",
            str(recipe.shots.duration_s * 30),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-video_track_timescale",
            "30000",
            "-preset",
            recipe.post.preset,
            "-crf",
            str(recipe.post.crf),
            "-threads",
            "1",
        ]
    else:
        args += ["-c:v", "copy"]
    args += [
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
