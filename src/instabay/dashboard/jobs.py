"""FR-01, FR-04, FR-09: one-click weekly generation from the owner dashboard.

Steps: freeze the brand with the owner's name, swap gpu-box from the image models to the caption
model, run the existing non-demo week (planner → briefs → EN/AR copy → checks → photo renders),
then swap back. It stops at the approval queue like the CLI; it never approves or publishes.
"""

import json
import subprocess
import threading
import time
import traceback
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Protocol

import httpx
from pydantic import Field

from instabay.adapters.cassette import RecordingLLMClient
from instabay.adapters.llm import LLMClient
from instabay.assets.export import export_library
from instabay.assets.library import AssetLibrary
from instabay.assets.plan import load_cadence, suggest_assets
from instabay.content.production import generate_week
from instabay.core.schemas import Boundary, BrandConstitution, Slot
from instabay.llm import RunBudget
from instabay.repository import Repository

CAPTION_MODEL = "Qwen/Qwen3-8B:nf4@b968826d9c46dd6066d109eabc6255188de91218"
REMOTE = "/home/mazen/instabay-native"
PYTHON = "/home/mazen/miniconda3/envs/main/bin/python"
STEPS = ("Check photos", "Freeze brand", "Load caption model", "Write the week", "Free the GPU")
StepState = Literal["waiting", "running", "done", "failed"]


class Step(Boundary):
    name: str
    state: StepState = "waiting"
    detail: str = ""
    seconds: float | None = None


class JobStatus(Boundary):
    id: str
    run_id: str
    output: str
    started_at: str
    state: Literal["running", "done", "failed"]
    steps: list[Step]
    error: str | None = None
    posts: int = Field(default=0, ge=0)


class GpuControl(Protocol):
    """NFR-06: one large model resident on the 16 GB card at a time."""

    def caption_up(self) -> str: ...

    def caption_down(self) -> None: ...


def run(command: list[str], timeout: float = 60) -> None:
    subprocess.run(command, check=True, timeout=timeout, capture_output=True)


class SSHGpuControl:
    """HUMAN-enabled gpu-box orchestration over SSH/tmux, the same commands as the runbooks."""

    def __init__(self, host: str = "gpu-box", port: int = 18765) -> None:
        self.host, self.port = host, port
        self.origin = f"http://127.0.0.1:{port}"

    def caption_up(self) -> str:
        run(["ssh", self.host, "tmux kill-session -t instabay-vision 2>/dev/null; true"])
        run(
            [
                "ssh",
                self.host,
                "tmux has-session -t instabay-caption 2>/dev/null || "
                f'(cd {REMOTE} && tmux new -d -s instabay-caption "INSTABAY_LLM_ENABLED=1 '
                f"{PYTHON} -m uvicorn gpu_worker.caption_llm_server:app --host 127.0.0.1 "
                '--port 8765 >> outputs/instabay-caption.log 2>&1")',
            ]
        )
        if not self._healthy():
            run(
                [
                    "ssh", "-f", "-N", "-o", "ExitOnForwardFailure=yes",
                    "-o", "ServerAliveInterval=30",
                    "-L", f"127.0.0.1:{self.port}:127.0.0.1:8765", self.host,
                ]
            )  # fmt: skip
        deadline = time.monotonic() + 120
        while not self._healthy():
            if time.monotonic() > deadline:
                raise RuntimeError("Caption service did not start on gpu-box")
            time.sleep(2)
        response = httpx.post(self.origin + "/warm", timeout=900, trust_env=False)
        if response.status_code != 200:
            raise RuntimeError(f"Caption model failed to load (HTTP {response.status_code})")
        return self.origin

    def _healthy(self) -> bool:
        try:
            return httpx.get(self.origin + "/health", timeout=3, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    def caption_down(self) -> None:
        run(["ssh", self.host, "tmux kill-session -t instabay-caption 2>/dev/null; true"])
        subprocess.run(["pkill", "-f", f"{self.port}:127.0.0.1:8765"], check=False)
        run(
            [
                "ssh",
                self.host,
                "tmux has-session -t instabay-vision 2>/dev/null || "
                f'(cd {REMOTE} && tmux new -d -s instabay-vision "PYTHONPATH=data/pydeps-d3:. '
                f"INSTABAY_GPU_ENABLED=1 PYTHONUNBUFFERED=1 {PYTHON} -m uvicorn "
                "gpu_worker.vision_server:app --host 127.0.0.1 --port 8790 "
                '>> outputs/instabay-vision.log 2>&1")',
            ]
        )


def next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return date.fromordinal(today.toordinal() + (7 - today.weekday()))


class Generator:
    """FR-09: one job at a time; state is written to disk so a page reload can follow it."""

    def __init__(
        self,
        *,
        root: Path,
        runs: Path,
        workspace: Path,
        brand: BrandConstitution,
        gpu: GpuControl,
        client_factory: Callable[[str], LLMClient],
        model: str = CAPTION_MODEL,
    ) -> None:
        self.root, self.runs, self.workspace, self.brand = root, runs, workspace, brand
        self.gpu, self.client_factory, self.model = gpu, client_factory, model
        self.lock = threading.Lock()
        self.status: JobStatus | None = None
        self.thread: threading.Thread | None = None

    def current(self) -> JobStatus | None:
        return self.status

    def start(self, actor: str, week_start: date, *, wait: bool = False) -> JobStatus:
        if self.thread and self.thread.is_alive():
            raise ValueError("A week is already being generated")
        if week_start.weekday() != 0:
            raise ValueError("A week starts on Monday")
        run_id = f"week-{week_start.isoformat()}"
        output = self.runs / run_id
        self.status = JobStatus(
            id=f"{run_id}-{int(time.time())}",
            run_id=run_id,
            output=output.relative_to(self.root).as_posix(),
            started_at=datetime.now(UTC).isoformat(),
            state="running",
            steps=[Step(name=n) for n in STEPS],
        )
        self._save()
        self.thread = threading.Thread(
            target=self._run, args=(actor, week_start, output), daemon=True
        )
        self.thread.start()
        if wait:
            self.thread.join()
        return self.status

    def _save(self) -> None:
        assert self.status is not None
        folder = self.runs / "jobs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "latest.json").write_text(self.status.model_dump_json(indent=2))

    def _step(self, index: int, state: StepState, detail: str = "", started: float = 0) -> None:
        assert self.status is not None
        steps = list(self.status.steps)
        steps[index] = steps[index].model_copy(
            update={
                "state": state,
                "detail": detail,
                "seconds": round(time.perf_counter() - started, 1) if started else None,
            }
        )
        self.status = self.status.model_copy(update={"steps": steps})
        self._save()

    def _run(self, actor: str, week_start: date, output: Path) -> None:
        index, started, gpu_used = 0, time.perf_counter(), False
        try:
            self._step(0, "running")
            with AssetLibrary(self.workspace, root=self.root) as library:
                evidence, _ = export_library(library, self.brand, self.workspace / "export")
                cadence = load_cadence(library, self.brand).cadence(self.brand)
                assets = library.all()
            ready = len(evidence.facts)
            self._step(0, "done", f"{ready} ready photos", started)

            index, started = 1, time.perf_counter()
            self._step(1, "running")
            output.mkdir(parents=True, exist_ok=True)
            repository = Repository(output / "posts.sqlite")
            try:
                digest = repository.register_brand(self.brand, actor=actor)
            finally:
                repository.close()
            self._step(1, "done", f"frozen by {actor} ({digest[:10]})", started)

            index, started = 2, time.perf_counter()
            self._step(2, "running", "stopping image models, loading Qwen3-8B")
            gpu_used = True
            origin = self.gpu.caption_up()
            self._step(2, "done", "Qwen3-8B ready", started)

            index, started = 3, time.perf_counter()
            self._step(3, "running", "planner → briefs → EN/AR captions → checks → photos")

            def pools(slots: list[Slot]) -> dict[str, list[str]]:
                return {k: v.pool for k, v in suggest_assets(slots, assets).items()}

            recorder = RecordingLLMClient(self.client_factory(origin), output / "cassette.json")
            try:
                result = generate_week(
                    brand=self.brand,
                    evidence=evidence,
                    catalog=evidence.objects(self.root),
                    root=self.root,
                    output=output,
                    run_id=self.status.run_id if self.status else output.name,
                    week_start=week_start,
                    model=self.model,
                    client=recorder,
                    budget=RunBudget(max_calls=70, max_tokens=200000, max_cost_usd=1),
                    draft_only=True,
                    cadence=cadence,
                    asset_pools=pools,
                )
            finally:
                recorder.close()
            assert self.status is not None
            self.status = self.status.model_copy(update={"posts": len(result.post_ids)})
            self._step(3, "done", f"{len(result.post_ids)} posts waiting for you", started)
        except Exception as error:
            self._step(index, "failed", str(error).splitlines()[0][:300], started)
            (self.runs / "jobs" / "latest.log").write_text(traceback.format_exc())
            assert self.status is not None
            self.status = self.status.model_copy(
                update={"state": "failed", "error": str(error).splitlines()[0][:300]}
            )
        finally:
            started = time.perf_counter()
            if gpu_used:
                try:
                    self._step(4, "running", "restarting image models")
                    self.gpu.caption_down()
                    self._step(4, "done", "image models back", started)
                except Exception as error:
                    self._step(4, "failed", str(error)[:300], started)
            else:
                self._step(4, "done", "not needed")
            assert self.status is not None
            if self.status.state == "running":
                self.status = self.status.model_copy(update={"state": "done"})
            self._save()


def load_latest(runs: Path) -> dict[str, object] | None:
    path = runs / "jobs" / "latest.json"
    return json.loads(path.read_text()) if path.exists() else None
