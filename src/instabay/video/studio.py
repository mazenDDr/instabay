"""FR-06, NFR-03: durable recipe ledger and verified artifact-addressed cache."""

import fcntl
import json
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import Field

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import Boundary, Hash
from instabay.repository import Repository
from instabay.video.backends.base import ShotRecipe, VideoBackend
from instabay.video.backends.stub import StubVideoBackend
from instabay.video.files import RenderError, digest, frame_hashes
from instabay.video.keyframes import runtime_identity, verify_inputs
from instabay.video.post import contact_sheet, post_process
from instabay.video.qa import VideoQA, VisualQA, evaluate


class RenderResult(Boundary):
    """FR-07, NFR-06: actual artifact hashes, timing and QA; no approval decision."""

    recipe_hash: Hash
    backend: Literal["stub", "wan", "comfyui", "veo"]
    file: str
    file_sha256: Hash
    contact_sheet: str
    contact_sha256: Hash
    frame_hashes: list[Hash] = Field(min_length=1)
    seconds: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    qa: VideoQA
    ai_disclosure: bool
    reference_only: bool
    determinism_level: Literal["L0"] = "L0"


class VideoStudio:
    """FR-06: one active job, durable ledger and fail-closed cached byte validation."""

    def __init__(
        self,
        db: Path,
        root: Path,
        renders: Path,
        backend: VideoBackend | None = None,
        visual: VisualQA | None = None,
    ) -> None:
        self.db, self.root, self.renders = db, root.resolve(), renders.resolve()
        self.backend = backend or StubVideoBackend()
        self.visual = visual
        # Reuse the additive domain schema, including render_job, without native initialization.
        repository = Repository(db)
        repository.close()
        self.renders.mkdir(parents=True, exist_ok=True)

    def _record(
        self, recipe: RenderRecipe, status: str, result: RenderResult | None = None
    ) -> None:
        with sqlite3.connect(self.db, timeout=30) as connection:
            connection.execute(
                "INSERT INTO render_job (recipe_hash,recipe_json,backend,status,gpu,seconds,"
                "frame_hashes_json,qa_json,cost_usd) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(recipe_hash) DO UPDATE SET status=excluded.status,"
                "seconds=excluded.seconds,"
                "frame_hashes_json=excluded.frame_hashes_json,qa_json=excluded.qa_json,cost_usd=excluded.cost_usd",
                (
                    recipe.recipe_hash,
                    recipe.model_dump_json(),
                    recipe.backend,
                    status,
                    recipe.runtime.gpu,
                    result.seconds if result else 0,
                    json.dumps(result.frame_hashes) if result else "[]",
                    result.model_dump_json() if result else "{}",
                    result.cost_usd if result else 0,
                ),
            )

    def _cached(self, recipe: RenderRecipe, directory: Path) -> RenderResult | None:
        manifest = directory / "result.json"
        if not manifest.exists():
            return None
        result = RenderResult.model_validate_json(manifest.read_bytes())
        with sqlite3.connect(self.db, timeout=30) as connection:
            row = connection.execute(
                "SELECT qa_json FROM render_job WHERE recipe_hash=? AND status='complete'",
                (recipe.recipe_hash,),
            ).fetchone()
        if row is not None and RenderResult.model_validate_json(row[0]) != result:
            raise RenderError("Cached result metadata differs from the stored render ledger")
        if (
            result.recipe_hash != recipe.recipe_hash
            or result.backend != recipe.backend
            or result.ai_disclosure != recipe.generated
            or result.reference_only != recipe.reference_only
            or Path(result.file).resolve() != directory / "reel.mp4"
            or Path(result.contact_sheet).resolve() != directory / "contact-sheet.jpg"
            or digest(Path(result.file)) != result.file_sha256
            or digest(Path(result.contact_sheet)) != result.contact_sha256
            or RenderRecipe.model_validate_json((directory / "recipe.json").read_bytes()) != recipe
        ):
            raise RenderError(
                "Cached artifact or provenance changed; automatic regeneration is forbidden"
            )
        return result

    def render(self, recipe: RenderRecipe) -> RenderResult:
        """NFR-03: recipe is stored before motion; a cache hit never calls a backend."""
        recipe = RenderRecipe.model_validate(recipe.model_dump())
        if recipe.backend != self.backend.name:
            raise RenderError("Requested backend differs from configured backend")
        verify_inputs(recipe, self.root)
        directory = self.renders / recipe.recipe_hash
        # OS lock is released on process death; no stale-running lock or concurrent GPU execution.
        with (self.renders / ".render.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            cached = self._cached(recipe, directory)
            if cached is not None:
                self._record(recipe, "complete", cached)
                return cached
            if recipe.backend != "stub" and (directory / "recipe.json").exists():
                raise RenderError(
                    "Incomplete native render needs HUMAN reconciliation before retry"
                )
            current = runtime_identity()
            for key in (
                "python",
                "platform",
                "ffmpeg_sha256",
                "ffprobe_sha256",
                "implementation_sha256",
                "pillow",
                "reshaper",
                "bidi",
            ):
                if getattr(recipe.runtime, key) != getattr(current, key):
                    raise RenderError("Runtime differs from recipe; prepare a new measured recipe")
            caps = self.backend.capabilities()
            if any(s.end_keyframe for s in recipe.shots.shots) and not caps.flf2v:
                raise RenderError("Configured backend cannot provide requested FLF")
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "recipe.json").write_text(
                recipe.model_dump_json(indent=2), encoding="utf-8"
            )
            self._record(recipe, "running")
            started = perf_counter()
            try:
                shots = [
                    self.backend.render_shot(
                        ShotRecipe(recipe=recipe, index=i), self.root, directory
                    )
                    for i in range(len(recipe.shots.shots))
                ]
                file = post_process(recipe, self.root, [Path(s.file) for s in shots], directory)
                qa = evaluate(file, recipe, self.visual)
                if not qa.spec_ok:
                    raise RenderError("Rendered media fails the actual reel specification")
                contact = contact_sheet(file, directory, recipe.shots.duration_s)
                result = RenderResult(
                    recipe_hash=recipe.recipe_hash,
                    backend=recipe.backend,
                    file=str(file),
                    file_sha256=digest(file),
                    contact_sheet=str(contact),
                    contact_sha256=digest(contact),
                    frame_hashes=frame_hashes(file),
                    seconds=perf_counter() - started,
                    cost_usd=sum(s.cost_usd for s in shots),
                    qa=qa,
                    ai_disclosure=recipe.generated,
                    reference_only=recipe.reference_only,
                )
                temporary = directory / ".result.pending"
                temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                temporary.replace(directory / "result.json")
                self._record(recipe, "complete", result)
                return result
            except Exception:
                self._record(recipe, "failed")
                raise
