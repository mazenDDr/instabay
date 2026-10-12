"""NFR-03, NFR-04: local hash verification and bounded sanitized external processes."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from instabay.video.shotlist import FileRef


class RenderError(RuntimeError):
    """FR-07: failed motion/post/QA stays unready and never becomes approved."""


def digest(path: Path) -> str:
    """NFR-03: stream file hashes without loading model weights into RAM."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_file(root: Path, ref: FileRef) -> Path:
    """NFR-04: reject traversal/symlink escape and changed source bytes."""
    path = (root / ref.uri).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or digest(path) != ref.sha256:
        raise RenderError("Input path or SHA-256 differs from the stored recipe")
    return path


def binary(name: str) -> Path:
    """FR-07: missing tools are explicit installation failures, never skipped QA."""
    path = shutil.which(name)
    if path is None:
        raise RenderError(f"Install {name} before rendering")
    return Path(path).resolve()


def command(args: list[str], timeout: int = 180, cwd: Path | None = None) -> bytes:
    """NFR-04: no shell; bounded output and no raw provider errors in logs."""
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=True, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        raise RenderError("Media subprocess failed; no artifact is ready") from None
    return result.stdout


def probe(path: Path) -> dict[str, Any]:
    """FR-07: typed QA consumes actual ffprobe output, never recipe estimates."""
    raw = command(
        [
            str(binary("ffprobe")),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    result: dict[str, Any] = json.loads(raw)
    return result


def frame_hashes(path: Path) -> list[str]:
    """NFR-03: SHA-256 of every decoded frame for measured local L1 comparisons."""
    raw = command(
        [
            str(binary("ffmpeg")),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "framehash",
            "-hash",
            "sha256",
            "-",
        ]
    )
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in raw.decode().splitlines()
        if line and not line.startswith("#")
    ]
