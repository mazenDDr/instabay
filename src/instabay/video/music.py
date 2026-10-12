"""FR-06: original deterministic preview score; never pretend it is recorded hotel ambience."""

import array
import math
import wave
from pathlib import Path
from typing import Protocol

from instabay.video.direction import VideoBoard
from instabay.video.files import digest
from instabay.video.shotlist import Audio, FileRef


class MusicProvider(Protocol):
    """NFR-05: licensed audio selection/synthesis stays separate from the video director."""

    def score(self, board: VideoBoard, root: Path, directory: Path) -> Audio: ...


class ProceduralPreviewMusic:
    """FR-06: calm harmonic bed and plucks cue the actual storyboard cuts; no external samples."""

    def score(self, board: VideoBoard, root: Path, directory: Path) -> Audio:
        """NFR-03: PCM bytes participate in the recipe; no recorded ambience claim."""
        duration = sum(b.frames for b in board.plan.beats) / 30
        rate = 48000
        step = 60 / board.plan.bpm
        data = array.array("h")
        frequencies = [293.665, 220.0, 349.228, 261.626]
        cues = [0.0]
        elapsed = 0
        for beat in board.plan.beats[:-1]:
            elapsed += beat.frames
            cues.append(elapsed / 30)
        cue_index = 0
        for index in range(round(duration * rate)):
            t = index / rate
            chord = min(3, int(t / (duration / 4)))
            fundamental = frequencies[chord]
            pad = (
                sum(
                    math.sin(2 * math.pi * f * t)
                    for f in (fundamental / 2, fundamental * 0.75, fundamental)
                )
                / 3
            )
            local = t % step
            note = [2, 3, 2.5, 3][int(t / step) % 4] * fundamental
            pluck = math.sin(2 * math.pi * note * t) * math.exp(-local * 9)
            bass = math.sin(2 * math.pi * (65 - local * 20) * local) * math.exp(-local * 24)
            if cue_index + 1 < len(cues) and t >= cues[cue_index + 1]:
                cue_index += 1
            cue_t = t - cues[cue_index]
            cue = 0.06 * math.sin(2 * math.pi * 880 * cue_t) * math.exp(-cue_t * 18)
            fade = max(0, min(1, t / 0.4, (duration - t) / 1.2))
            value = (0.12 * pad + 0.16 * pluck + 0.13 * bass + cue) * fade
            sample = round(value * 32767)
            data.extend([sample, sample])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "original-preview-score.pending.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(data.tobytes())
        sha = digest(path)
        immutable = directory / f"original-preview-score-{sha}.wav"
        path.replace(immutable)
        return Audio(
            music=FileRef(
                uri=immutable.resolve().relative_to(root.resolve()).as_posix(), sha256=sha
            ),
            music_credit=(
                "Original procedural preview score; synthesized tones, "
                "no external samples or field recordings"
            ),
        )
