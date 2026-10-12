"""FR-06: HUMAN-only private worker submission with bounded polling and verified downloads."""

import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from instabay.core.recipe import RenderRecipe
from instabay.video.backends.base import VideoBackend
from instabay.video.files import RenderError, digest
from instabay.video.studio import RenderResult
from instabay.video.worker import JobStatus


class RenderService(Protocol):
    """NFR-05: graph can use a local studio or explicitly configured private worker."""

    root: Path
    backend: VideoBackend

    def render(self, recipe: RenderRecipe) -> RenderResult: ...


class WorkerClient:
    """NFR-04: explicit opt-in, no public endpoint, credentials in headers only."""

    def __init__(
        self,
        origin: str,
        auth_token: str,
        root: Path,
        renders: Path,
        backend: VideoBackend,
        *,
        confirm_worker: bool = False,
        transport: httpx.BaseTransport | None = None,
        polls: int = 120,
        poll_seconds: float = 5,
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"gpu-box", "100.109.90.64", "127.0.0.1", "localhost"}
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Worker must be a private Tailscale or loopback origin")
        if len(auth_token) < 24 or not 1 <= polls <= 720 or not 0 <= poll_seconds <= 10:
            raise ValueError("Worker credentials and polling budget are required")
        self.root, self.renders, self.backend = root.resolve(), renders.resolve(), backend
        self.confirm_worker, self.polls, self.poll_seconds = confirm_worker, polls, poll_seconds
        self.client = httpx.Client(
            base_url=origin,
            transport=transport,
            timeout=30,
            trust_env=False,
            headers={"x-instabay-worker-key": auth_token},
        )

    def close(self) -> None:
        """NFR-06: release private transport resources."""
        self.client.close()

    def render(self, recipe: RenderRecipe) -> RenderResult:
        """FR-06: idempotent POST, bounded backoff poll, checksum-verified local preview."""
        if not self.confirm_worker:
            raise RenderError("HUMAN: explicitly authorize worker execution")
        if recipe.backend != self.backend.name:
            raise RenderError("Worker client backend differs from recipe")
        try:
            response = self.client.post("/jobs", json=recipe.model_dump(mode="json"))
            response.raise_for_status()
            job = JobStatus.model_validate(response.json())
            if job.id != recipe.recipe_hash:
                raise RenderError("Worker returned a different recipe hash")
            for attempt in range(self.polls):
                if job.status == "complete":
                    break
                if job.status == "failed":
                    raise RenderError("Worker failed; HUMAN reconciliation required")
                time.sleep(min(10, self.poll_seconds * (1.5 ** min(attempt, 5))))
                response = self.client.get(f"/jobs/{recipe.recipe_hash}")
                response.raise_for_status()
                job = JobStatus.model_validate(response.json())
                if job.id != recipe.recipe_hash:
                    raise RenderError("Worker identity changed")
            if job.status != "complete":
                raise RenderError("Worker polling budget exhausted; job remains stored")
            directory = self.renders / recipe.recipe_hash
            directory.mkdir(parents=True, exist_ok=True)

            def download(name: str) -> bytes:
                result = self.client.get(f"/jobs/{recipe.recipe_hash}/artifacts/{name}")
                result.raise_for_status()
                if len(result.content) > recipe.post.max_bytes:
                    raise RenderError("Worker artifact exceeds configured bound")
                return result.content

            remote = RenderResult.model_validate_json(download("result.json"))
            stored = RenderRecipe.model_validate_json(download("recipe.json"))
            if (
                stored != recipe
                or remote.recipe_hash != recipe.recipe_hash
                or remote.backend != recipe.backend
                or remote.ai_disclosure != recipe.generated
                or remote.reference_only != recipe.reference_only
                or not remote.qa.spec_ok
            ):
                raise RenderError("Worker result does not match submitted provenance")
            for name, sha in [
                ("reel.mp4", remote.file_sha256),
                ("contact-sheet.jpg", remote.contact_sha256),
            ]:
                pending = directory / f".{name}.pending"
                pending.write_bytes(download(name))
                if digest(pending) != sha:
                    raise RenderError("Downloaded worker bytes failed SHA-256")
                pending.replace(directory / name)
            result = RenderResult.model_validate(
                remote.model_dump()
                | {
                    "file": str(directory / "reel.mp4"),
                    "contact_sheet": str(directory / "contact-sheet.jpg"),
                }
            )
            (directory / "recipe.json").write_text(recipe.model_dump_json(indent=2))
            (directory / "result.json").write_text(result.model_dump_json(indent=2))
            return result
        except RenderError:
            raise
        except Exception:
            raise RenderError(
                "Worker request failed; inspect the stored job, not raw credentials"
            ) from None
