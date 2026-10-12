"""FR-06, NFR-04: HUMAN: run on gpu-box, bind Tailscale and restrict tagged-device ACLs."""

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from instabay.core.recipe import RenderRecipe
from instabay.video.backends.comfyui import ComfyUIBackend
from instabay.video.backends.wan_diffusers import WanDiffusersBackend
from instabay.video.keyframes import verify_inputs
from instabay.video.studio import VideoStudio
from instabay.video.worker import JobStatus, RenderQueue


def create_app(studio: VideoStudio, auth_token: str, *, process_jobs: bool = False) -> FastAPI:
    """NFR-04: no unauthenticated jobs/artifacts; no implicit GPU work during import."""
    if len(auth_token) < 24:
        raise ValueError("Set a worker token of at least 24 characters in .env")
    queue = RenderQueue(studio)
    stop = Event()

    def work() -> None:
        while not stop.is_set():
            queue.run_once()
            stop.wait(1)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        thread = Thread(target=work, daemon=True)
        if process_jobs:
            thread.start()
        yield
        stop.set()
        if process_jobs:
            thread.join(timeout=5)

    app = FastAPI(title="Insta Bay private render worker", lifespan=lifespan)
    app.state.queue = queue

    def authenticate(x_instabay_worker_key: Annotated[str | None, Header()] = None) -> None:
        if x_instabay_worker_key is None or not secrets.compare_digest(
            x_instabay_worker_key, auth_token
        ):
            raise HTTPException(status_code=401, detail="Worker authorization required")

    auth = [Depends(authenticate)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "backend": studio.backend.name}

    @app.post("/jobs", dependencies=auth, response_model=JobStatus, status_code=202)
    def submit(recipe: RenderRecipe) -> JobStatus:
        if recipe.backend != studio.backend.name:
            raise HTTPException(status_code=422, detail="Worker backend differs from recipe")
        return queue.submit(recipe)

    @app.get("/jobs/{job_id}", dependencies=auth, response_model=JobStatus)
    def status(job_id: str) -> JobStatus:
        try:
            return queue.status(job_id)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail="Unknown job") from None

    @app.get("/jobs/{job_id}/artifacts/{name}", dependencies=auth)
    def artifact(job_id: str, name: str) -> FileResponse:
        if name not in {"reel.mp4", "contact-sheet.jpg", "recipe.json", "result.json"}:
            raise HTTPException(status_code=404, detail="Unknown artifact")
        job = status(job_id)
        if job.status != "complete":
            raise HTTPException(status_code=409, detail="Artifact is not complete")
        # Verify the stored recipe/artifact bytes before serving, including cache tampering.
        directory = studio.renders / job.id
        try:
            if not (directory / "result.json").is_file():
                raise ValueError("Complete job has lost its artifact manifest")
            recipe = RenderRecipe.model_validate_json((directory / "recipe.json").read_bytes())
            studio.render(recipe)
        except Exception:
            raise HTTPException(status_code=409, detail="Artifact verification failed") from None
        return FileResponse(directory / name)

    return app


def app_from_env() -> FastAPI:
    """NFR-04: HUMAN: launch this factory only on the restricted Tailscale machine."""
    token = os.environ.get("INSTABAY_WORKER_TOKEN", "")
    root = Path(os.environ.get("INSTABAY_WORKER_ROOT", "."))
    backend = os.environ.get("INSTABAY_VIDEO_BACKEND", "stub")
    studio = VideoStudio(
        Path(os.environ.get("INSTABAY_DB_PATH", "outputs/worker.sqlite3")),
        root,
        Path(os.environ.get("INSTABAY_RENDERS_PATH", "renders")),
        WanDiffusersBackend(confirm_gpu=True)
        if backend == "wan"
        else ComfyUIBackend(confirm_gpu=True)
        if backend == "comfyui"
        else None,
    )
    if backend not in {"stub", "wan", "comfyui"}:
        raise ValueError("Unsupported worker backend")
    if backend != "stub":
        recipe_path = os.environ.get("INSTABAY_WORKER_RECIPE")
        if not recipe_path:
            raise ValueError("HUMAN: supply a pinned startup recipe before native jobs")
        recipe = RenderRecipe.model_validate_json(Path(recipe_path).read_bytes())
        if recipe.backend != backend:
            raise ValueError("Startup recipe differs from worker backend")
        verify_inputs(recipe, root)
    return create_app(studio, token, process_jobs=True)
