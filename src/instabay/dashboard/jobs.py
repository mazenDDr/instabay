"""FR-01, FR-04, FR-06, FR-09: the weekly pipeline behind the dashboard, in two modes.

Autopilot runs every stage and stops at the owner's post approval. Step by step pauses after
each stage so the owner can look, fix pillars or approve new shots, then press Continue.
Stages: sort photos → plan the week → new shots for gaps → freeze brand → write the week.
Nothing is approved or published here.
"""

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
from instabay.assets.classify import classify_assets
from instabay.assets.export import export_library
from instabay.assets.judge import PillarJudge
from instabay.assets.library import NEAR_COPY, VIEW_OK, Asset, AssetLibrary, distance
from instabay.assets.plan import Suggestion, load_cadence, suggest_assets
from instabay.assets.variants import ViewBackend, check_fidelity, make_shot
from instabay.content.production import generate_week
from instabay.core.planner import plan_week
from instabay.core.schemas import Boundary, BrandConstitution, Slot, canonical_hash
from instabay.decisions.vision import VisionDecisionEngine
from instabay.llm import RunBudget
from instabay.repository import Repository

WRITER_MODEL = "Qwen/Qwen3.5-9B:nf4@c202236235762e1c871ad0ccb60c8ee5ba337b9a"
REMOTE = "/home/mazen/instabay-native"
PYTHON = "/home/mazen/miniconda3/envs/main/bin/python"
STAGES = (
    ("sort", "Sort photos into pillars"),
    ("plan", "Plan the week"),
    ("shots", "New shots for missing photos"),
    ("freeze", "Freeze brand"),
    ("write", "Write the week"),
)
Mode = Literal["autopilot", "guided"]
StepState = Literal["waiting", "running", "done", "failed", "skipped"]
MAX_NEW_SHOTS = 8


class Step(Boundary):
    key: str
    name: str
    state: StepState = "waiting"
    detail: str = ""
    seconds: float | None = None


class JobStatus(Boundary):
    id: str
    mode: Mode
    run_id: str
    output: str
    started_at: str
    state: Literal["running", "paused", "done", "failed"]
    steps: list[Step]
    paused_after: str | None = None
    error: str | None = None
    posts: int = Field(default=0, ge=0)
    new_shots: list[str] = Field(default_factory=list)


class VisionService(Protocol):
    """NFR-06: the gpu-box service hosting d3-flash, Qwen3.5-9B and FLUX (one at a time)."""

    def ensure(self) -> str: ...


class SSHVisionService:
    """HUMAN-enabled: the same commands as `make vision-up`."""

    def __init__(self, host: str = "gpu-box", port: int = 18790) -> None:
        self.host, self.port = host, port
        self.origin = f"http://127.0.0.1:{port}"

    def _healthy(self) -> bool:
        try:
            return httpx.get(self.origin + "/health", timeout=3, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    def ensure(self) -> str:
        if self._healthy():
            return self.origin
        subprocess.run(
            [
                "ssh",
                self.host,
                "tmux has-session -t instabay-vision 2>/dev/null || "
                f'(cd {REMOTE} && tmux new -d -s instabay-vision "PYTHONPATH=data/pydeps-d3:. '
                f"INSTABAY_GPU_ENABLED=1 INSTABAY_LLM_ENABLED=1 PYTHONUNBUFFERED=1 {PYTHON} -m "
                "uvicorn gpu_worker.vision_server:app --host 127.0.0.1 --port 8790 "
                '>> outputs/instabay-vision.log 2>&1")',
            ],
            check=True,
            timeout=60,
            capture_output=True,
        )
        subprocess.run(
            [
                "ssh", "-f", "-N", "-o", "ExitOnForwardFailure=yes",
                "-L", f"127.0.0.1:{self.port}:127.0.0.1:8790", self.host,
            ],
            check=False,
            timeout=60,
            capture_output=True,
        )  # fmt: skip
        deadline = time.monotonic() + 90
        while not self._healthy():
            if time.monotonic() > deadline:
                raise RuntimeError("The gpu-box service did not start (is the PC on?)")
            time.sleep(2)
        return self.origin


def next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return date.fromordinal(today.toordinal() + (7 - today.weekday()))


class Pipeline:
    """FR-09: one run at a time; status lives on disk so a page reload can follow it."""

    def __init__(
        self,
        *,
        root: Path,
        runs: Path,
        workspace: Path,
        brand: BrandConstitution,
        service: VisionService,
        engine: VisionDecisionEngine | None,
        judge: PillarJudge | None,
        views: ViewBackend | None,
        view_revision: str,
        client_factory: Callable[[str], LLMClient],
        model: str = WRITER_MODEL,
        multimodal: bool = True,
    ) -> None:
        self.root, self.runs, self.workspace, self.brand = root, runs, workspace, brand
        self.service, self.engine, self.judge, self.views = service, engine, judge, views
        self.view_revision, self.client_factory, self.model = view_revision, client_factory, model
        self.multimodal = multimodal
        self.status: JobStatus | None = None
        self.thread: threading.Thread | None = None
        self.resume_event = threading.Event()

    def current(self) -> JobStatus | None:
        return self.status

    def start(self, actor: str, week_start: date, mode: Mode, *, wait: bool = False) -> JobStatus:
        if self.thread and self.thread.is_alive():
            raise ValueError("A week is already being prepared")
        if week_start.weekday() != 0:
            raise ValueError("A week starts on Monday")
        run_id = f"week-{week_start.isoformat()}"
        output = self.runs / run_id
        self.status = JobStatus(
            id=f"{run_id}-{int(time.time())}",
            mode=mode,
            run_id=run_id,
            output=output.relative_to(self.root).as_posix(),
            started_at=datetime.now(UTC).isoformat(),
            state="running",
            steps=[Step(key=k, name=n) for k, n in STAGES],
        )
        self._save()
        self.resume_event.clear()
        self.thread = threading.Thread(
            target=self._run, args=(actor, week_start, output, mode), daemon=True
        )
        self.thread.start()
        if wait:
            self.thread.join()
        return self.status

    def resume(self) -> JobStatus:
        """FR-09: step-by-step mode continues only on the owner's click."""
        if self.status is None or self.status.state != "paused":
            raise ValueError("Nothing is waiting for you")
        self._update(state="running", paused_after=None)
        self.resume_event.set()
        return self.status

    # -- internals -------------------------------------------------------------------------

    def _save(self) -> None:
        assert self.status is not None
        folder = self.runs / "jobs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "latest.json").write_text(self.status.model_dump_json(indent=2))

    def _update(self, **fields: object) -> None:
        assert self.status is not None
        self.status = self.status.model_copy(update=fields)
        self._save()

    def _step(self, key: str, state: StepState, detail: str = "", started: float = 0) -> None:
        assert self.status is not None
        steps = [
            s.model_copy(
                update={
                    "state": state,
                    "detail": detail,
                    "seconds": round(time.perf_counter() - started, 1) if started else None,
                }
            )
            if s.key == key
            else s
            for s in self.status.steps
        ]
        self._update(steps=steps)

    def _pause(self, key: str, mode: Mode) -> None:
        if mode != "guided" or key == STAGES[-1][0]:
            return
        self.resume_event.clear()
        self._update(state="paused", paused_after=key)
        self.resume_event.wait()

    def _library(self) -> AssetLibrary:
        return AssetLibrary(self.workspace, root=self.root)

    def _slots(self, week_start: date) -> tuple[list[Slot], list[Asset]]:
        with self._library() as library:
            rhythm = load_cadence(library, self.brand).cadence(self.brand)
            assets = library.all()
        slots = plan_week(
            self.brand, canonical_hash(self.brand), "preview", week_start, cadence=rhythm
        )
        return slots, assets

    def _run(self, actor: str, week_start: date, output: Path, mode: Mode) -> None:
        key, started = "sort", time.perf_counter()
        try:
            # 1. Sort: only photos that have no pillar yet.
            self._step(key, "running")
            with self._library() as library:
                unsorted = [a for a in library.all() if a.pillar is None and not a.rejected]
                if unsorted and self.engine is not None:
                    self.service.ensure()
                    report = classify_assets(library, self.engine, self.brand, judge=self.judge)
                    detail = f"{report.classified} sorted, {report.judged} by the VLM judge"
                else:
                    detail = "all photos already have a pillar"
            self._step(key, "done", detail, started)
            self._pause(key, mode)

            # 2. Plan: slots and the photos reserved for each post.
            key, started = "plan", time.perf_counter()
            self._step(key, "running")
            slots, assets = self._slots(week_start)
            plan = suggest_assets(slots, assets)
            missing = {s.id: plan[s.id].missing for s in slots if plan[s.id].missing}
            self._step(
                key,
                "done",
                f"{len(slots)} posts; {sum(missing.values())} images missing for their pillar",
                started,
            )
            self._pause(key, mode)

            # 3. New shots: only where a post lacks images of its own pillar.
            key, started = "shots", time.perf_counter()
            if not missing or self.views is None:
                self._step(
                    key,
                    "skipped",
                    "no gaps" if not missing else "camera views are off",
                    started,
                )
            else:
                self._step(key, "running", "creating new shots with FLUX.2-klein")
                created, kept, empty = self._fill(slots, plan, mode)
                self._update(new_shots=created)
                self._step(
                    key,
                    "done",
                    f"{len(created)} new shots; "
                    + (
                        f"{kept} kept (same place ≥ {VIEW_OK:.0%}, not a near-copy)"
                        if mode == "autopilot"
                        else f"{kept} look good; approve the ones you like in Media"
                    )
                    + (
                        f". No photos for {', '.join(empty)}: add some, nothing was invented"
                        if empty
                        else ""
                    ),
                    started,
                )
                self._pause(key, mode)

            # 4. Freeze: the owner ticked the brand confirmation when starting.
            key, started = "freeze", time.perf_counter()
            self._step(key, "running")
            output.mkdir(parents=True, exist_ok=True)
            repository = Repository(output / "posts.sqlite")
            try:
                digest = repository.register_brand(self.brand, actor=actor)
            finally:
                repository.close()
            self._step(key, "done", f"frozen by {actor} ({digest[:10]})", started)

            # 5. Write: planner → visual briefs → EN/AR captions → checks → photo layouts.
            key, started = "write", time.perf_counter()
            self._step(
                key, "running", "briefs → English and Arabic captions → photos → reel videos"
            )
            result = self._write(week_start, output)
            self._update(posts=len(result))
            self._step(key, "done", f"{len(result)} posts waiting for your approval", started)
            self._update(state="done")
        except Exception as error:
            message = str(error).splitlines()[0][:300] if str(error) else type(error).__name__
            self._step(key, "failed", message, started)
            (self.runs / "jobs" / "latest.log").write_text(traceback.format_exc())
            self._update(state="failed", error=message)

    def _fill(
        self, slots: list[Slot], plan: dict[str, Suggestion], mode: Mode
    ) -> tuple[list[str], int, list[str]]:
        """FR-06: new shots only from owner photos of the same pillar; never invent a pillar.

        Autopilot keeps a shot when d3 says it is the same place (>= VIEW_OK) and it is not a
        near-copy of its source. d3's photoreal answer is shown but not used to decide: it rated
        clearly real room shots 0.45-0.59 on the owner's photos (2026-10-13).
        """
        assert self.views is not None
        self.service.ensure()
        created: list[str] = []
        empty: list[str] = []
        with self._library() as library:
            owners = [a for a in library.all() if a.origin == "owner" and a.usable]
            for slot in slots:
                need, pillar = plan[slot.id].missing, slot.arm.pillar
                sources = [a for a in owners if a.pillar == pillar]
                if need and not sources:
                    if pillar not in empty:
                        empty.append(pillar)
                    continue
                for n in range(need):
                    if len(created) >= MAX_NEW_SHOTS:
                        break
                    parents = [sources[n % len(sources)]]
                    if len(sources) > 1:
                        parents.append(sources[(n + 1) % len(sources)])
                    shot = make_shot(
                        library,
                        parents,
                        pillar,
                        variant=n,
                        seed=len(created),
                        backend=self.views,
                        revision=self.view_revision,
                    )
                    if shot.id not in created:
                        created.append(shot.id)
            if self.engine is not None:
                for shot_id in created:
                    check_fidelity(library, library.get(shot_id), self.engine)
            kept = 0
            for shot_id in created:
                shot = library.get(shot_id)
                parents = [library.get(str(p)) for p in (shot.recipe or {}).get("parents") or []]  # type: ignore[union-attr]
                copy = any(
                    distance(library.path(shot), library.path(p)) < NEAR_COPY for p in parents
                )
                same = (shot.fidelity or {}).get("same_place")
                good = isinstance(same, float) and same >= VIEW_OK and not copy
                library.record_fidelity(
                    shot_id, {**(shot.fidelity or {}), "near_copy": copy, "kept": good}
                )
                if mode == "autopilot":
                    library.review(shot_id, approved=good, rejected=not good)
                kept += good
        return created, kept, empty

    def _write(self, week_start: date, output: Path) -> list[str]:
        origin = self.service.ensure()
        with self._library() as library:
            evidence, _ = export_library(library, self.brand, self.workspace / "export")
            cadence = load_cadence(library, self.brand).cadence(self.brand)
            assets = library.all()

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
                run_id=output.name,
                week_start=week_start,
                model=self.model,
                client=recorder,
                budget=RunBudget(max_calls=80, max_tokens=300000, max_cost_usd=1),
                draft_only=False,
                cadence=cadence,
                asset_pools=pools,
                multimodal=self.multimodal,
            )
        finally:
            recorder.close()
        return list(result.post_ids)
