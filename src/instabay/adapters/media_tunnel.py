"""FR-07, FR-10: expose one approved post's exact photos over a short-lived public HTTPS tunnel.

Instagram downloads media from a public URL. Until a permanent bucket exists, the owner's Mac
serves only the post's files (named by SHA-256) through a Cloudflare quick tunnel, for the few
minutes the publish takes. The URL is bound into the media manifest, so the owner approves the
exact link and bytes, and the verifier re-downloads them before any container is created.
"""

import hashlib
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from instabay.core.schemas import MediaAsset, MediaManifest, Post

TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
# Instagram feed images: JPEG, aspect ratio from 4:5 to 1.91:1 [verify against Meta docs].
MIN_ASPECT, MAX_ASPECT = 0.8, 1.91


def tunnel_url(line: str) -> str | None:
    """FR-10: the quick-tunnel address cloudflared prints once it is connected."""
    match = TUNNEL_URL.search(line)
    return match.group(0) if match else None


def photo_files(post: Post, root: Path) -> list[Path]:
    """FR-07: the exact approved preview files; any byte change since approval stops here."""
    if post.format not in {"photo", "carousel"} or post.photo_artifact is None:
        raise ValueError("Only photo and carousel posts can be published this way for now")
    if post.photo_artifact.reference_only:
        raise ValueError("Reference-only photos cannot be published")
    files = []
    for preview in post.photo_artifact.files:
        path = Path(preview.file) if Path(preview.file).is_absolute() else root / preview.file
        if hashlib.sha256(path.read_bytes()).hexdigest() != preview.file_sha256:
            raise ValueError(f"{path.name} changed after it was generated")
        files.append(path)
    return files


def manifest(post: Post, files: list[Path], base_url: str, actor: str) -> MediaManifest:
    """FR-07: one image asset per file, URL named by content hash, specs read from the bytes."""
    assets = []
    for path in files:
        data = path.read_bytes()
        with Image.open(path) as image:
            if image.format != "JPEG" or image.mode != "RGB":
                raise ValueError(f"{path.name} must be an RGB JPEG")
            width, height = image.size
        if not MIN_ASPECT <= width / height <= MAX_ASPECT:
            raise ValueError(f"{path.name} is {width}x{height}; Instagram needs 4:5 to 1.91:1")
        digest = hashlib.sha256(data).hexdigest()
        assets.append(
            MediaAsset(
                url=f"{base_url}/{digest}.jpg",
                content_sha256=digest,
                kind="image",
                size_bytes=len(data),
                width=width,
                height=height,
                mime_type="image/jpeg",
                color_space="sRGB",
            )
        )
    assert post.photo_artifact is not None
    return MediaManifest(
        format=post.format,
        assets=assets,
        reference_only=False,
        verified_by=f"{actor} (instagram-post: bytes match the approved preview)",
        generated=post.photo_artifact.generated,
    )


def ready(post: Post, media: MediaManifest) -> Post:
    """FR-09: a new revision; its new content hash means the owner must approve it again."""
    return Post.model_validate(
        {
            **post.model_dump(),
            "media_manifest": media.model_dump(),
            "media_status": "ready",
            "revision": post.revision + 1,
        }
    )


class _Files(SimpleHTTPRequestHandler):
    """NFR-04: serves only `<sha256>.jpg` files from one temporary folder; no listings."""

    def do_GET(self) -> None:
        if not re.fullmatch(r"/[0-9a-f]{64}\.jpg", self.path):
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        self.do_GET()

    def guess_type(self, path: Any) -> str:
        return "image/jpeg"

    def log_message(self, format: str, *args: Any) -> None:
        return


@contextmanager
def public_files(files: list[Path], *, timeout_s: float = 180) -> Iterator[str]:
    """FR-10: yields the public base URL; the server and tunnel stop when the block ends."""
    if shutil.which("cloudflared") is None:
        raise RuntimeError("Install cloudflared first: brew install cloudflared")
    folder = Path(tempfile.mkdtemp(prefix="instabay-media-"))
    for path in files:
        shutil.copyfile(path, folder / f"{hashlib.sha256(path.read_bytes()).hexdigest()}.jpg")
    server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: _Files(*a, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = subprocess.Popen(
        [
            "cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{server.server_address[1]}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base = _wait_for_url(process, timeout_s)
        _wait_until_public(f"{base}/{next(folder.iterdir()).name}", timeout_s)
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        server.shutdown()
        server.server_close()
        shutil.rmtree(folder, ignore_errors=True)


def _wait_for_url(process: subprocess.Popen[str], timeout_s: float) -> str:
    assert process.stderr is not None
    found: list[str] = []

    def read() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            if not found and (url := tunnel_url(line)):
                found.append(url)

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout_s
    while not found:
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("The Cloudflare tunnel did not start; check your internet")
        time.sleep(0.5)
    return found[0]


def _wait_until_public(url: str, timeout_s: float) -> None:
    """FR-10: a new quick-tunnel name needs a few seconds before DNS and routing work."""
    deadline = time.monotonic() + timeout_s
    with httpx.Client(timeout=10, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(2)
    raise RuntimeError("The tunnel started but the photo is not reachable from the internet")
