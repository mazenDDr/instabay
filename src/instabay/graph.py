"""FR-09, FR-10: persistent LangGraph interrupt; resume reads stored human decisions only."""

from contextlib import ExitStack
from pathlib import Path
from typing import Literal, Protocol, Self, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context
from pydantic import TypeAdapter

from instabay.adapters.fake_llm import FakeLLM
from instabay.adapters.llm import LLMClient
from instabay.adapters.publisher import DryRunPublisher
from instabay.agents.brand_architect import BrandArchitect
from instabay.agents.brief_writer import BriefWriter
from instabay.agents.common import prompt_hashes
from instabay.agents.judge import Judge, write_bilingual
from instabay.agents.video_director import VideoDirector
from instabay.core.hashtags import select_hashtags
from instabay.core.planner import plan_week
from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import (
    BrandInput,
    PlanningPreferences,
    Post,
    RenderAttachment,
    WorkflowInput,
    WorkflowResult,
)
from instabay.db import SQLiteCallStore
from instabay.decisions.calibration import CalibrationProfile
from instabay.decisions.cascade import CheckCascade
from instabay.decisions.engine import DecisionEngine
from instabay.llm import LLMService, RunUsage
from instabay.repository import Repository
from instabay.video.direction import ObjectCatalog
from instabay.video.direction_commands import editorial_recipe
from instabay.video.keyframes import stub_recipe
from instabay.video.remote import RenderService
from instabay.video.shotlist import Keyframe


class ApprovalPendingError(PermissionError):
    """FR-09: resume cannot substitute an untrusted graph payload for stored decisions."""


class WeekState(TypedDict):
    """FR-03, FR-09: checkpoint data contains validated IDs, not provider credentials."""

    run_id: str
    week_start: str
    demo: bool
    brand_hash: str
    post_ids: list[str]
    status: Literal["planned", "drafted", "checked", "completed"]


class WorkflowRunner(Protocol):
    """NFR-05: isolate graph orchestration from CLI commands."""

    def start(self, request: WorkflowInput) -> WorkflowResult:
        """FR-09: stop at a persistent human-approval interrupt."""
        ...

    def resume(self, run_id: str) -> WorkflowResult:
        """FR-09: publish only after every post has a current stored decision."""
        ...


class WeekRunner:
    """FR-09: an offline graph that survives command/process restarts."""

    def __init__(
        self,
        db: Path,
        checkpoints: Path,
        outbox: Path,
        brand_input: BrandInput,
        fixtures: Path = Path("tests/fixtures/llm"),
        preferences: PlanningPreferences | None = None,
        decision_engine: DecisionEngine | None = None,
        calibration: CalibrationProfile | None = None,
        allow_synthetic_decisions: bool = False,
        video_studio: RenderService | None = None,
        approved_stills: list[Keyframe] | None = None,
        llm_client: LLMClient | None = None,
        model_overrides: dict[str, str] | None = None,
        token_overrides: dict[str, int] | None = None,
        render_recipes: dict[str, RenderRecipe] | None = None,
        video_catalog: ObjectCatalog | None = None,
        allow_video_animatic: bool = False,
    ) -> None:
        self._stack = ExitStack()
        self.repository = Repository(db)
        self._stack.callback(self.repository.close)
        self.calls = self._stack.enter_context(SQLiteCallStore(db))
        self.fake = FakeLLM(fixtures)
        self.video_catalog, self.allow_video_animatic = video_catalog, allow_video_animatic
        self.service = LLMService(
            llm_client or self.fake,
            self.calls,
            model_overrides=model_overrides,
            token_overrides=token_overrides,
        )
        self.brand_input = brand_input
        self.preferences = preferences
        self.decision_engine, self.calibration = decision_engine, calibration
        self.allow_synthetic_decisions = allow_synthetic_decisions
        self.video_studio, self.approved_stills = video_studio, approved_stills or []
        self.render_recipes = render_recipes or {}
        checkpoints.parent.mkdir(parents=True, exist_ok=True)
        saver = self._stack.enter_context(SqliteSaver.from_conn_string(str(checkpoints)))
        self.publisher = DryRunPublisher(self.repository, outbox)
        builder: StateGraph[WeekState, None, WeekState, WeekState] = StateGraph(WeekState)
        builder.add_node("brand", self._brand)
        builder.add_node("plan", self._plan)
        builder.add_node("draft", self._draft)
        builder.add_node("render_reel", self._render_reel)
        builder.add_node("checks", self._checks)
        builder.add_node("human_approval", self._human_approval)
        builder.add_node("publish", self._publish)
        for source, target in [
            (START, "brand"),
            ("brand", "plan"),
            ("plan", "draft"),
            ("draft", "render_reel"),
            ("render_reel", "checks"),
            ("checks", "human_approval"),
            ("human_approval", "publish"),
            ("publish", END),
        ]:
            builder.add_edge(source, target)
        self.graph: CompiledStateGraph[WeekState, None, WeekState, WeekState] = builder.compile(
            checkpointer=saver
        )

    @staticmethod
    def _config(run_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": run_id}, "recursion_limit": 20}

    def _brand(self, state: WeekState) -> dict[str, str]:
        constitution = BrandArchitect(self.service).draft(self.brand_input)
        digest = self.repository.register_brand(constitution)
        self.repository.start_run(
            WorkflowInput.model_validate(
                {
                    "run_id": state["run_id"],
                    "week_start": state["week_start"],
                    "demo": state["demo"],
                }
            ),
            digest,
        )
        return {"brand_hash": digest}

    def _plan(self, state: WeekState) -> dict[str, str]:
        if self.repository.slots(state["run_id"]):
            return {"status": "planned"}
        request = WorkflowInput.model_validate(
            {"run_id": state["run_id"], "week_start": state["week_start"], "demo": state["demo"]}
        )
        brand = self.repository.brand(state["brand_hash"])
        self.repository.save_slots(
            plan_week(
                brand, state["brand_hash"], request.run_id, request.week_start, self.preferences
            )
        )
        return {"status": "planned"}

    def _draft(self, state: WeekState) -> dict[str, object]:
        brand = self.repository.brand(state["brand_hash"])
        ids = []
        for slot in self.repository.slots(state["run_id"]):
            try:
                post = self.repository.post(slot.id)
            except KeyError:
                brief = BriefWriter(self.service).write(slot, brand)
                en, ar = write_bilingual(self.service, slot, brand, brief)
                post = Post(
                    id=slot.id,
                    slot_id=slot.id,
                    brand_hash=slot.brand_hash,
                    format=slot.arm.format,
                    brief=brief,
                    en=en,
                    ar=ar,
                    hashtags=select_hashtags(brand),
                    prompt_hashes=prompt_hashes(
                        self.service,
                        ["brand_architect", "brief_writer", "copy_en", "copy_ar", "judge"],
                    ),
                    media_path=brief.photo_uri if slot.arm.format != "reel" else None,
                    media_status="concept_only" if slot.arm.format == "reel" else "reference",
                )
                self.repository.save_post(post)
            ids.append(post.id)
        return {"post_ids": ids, "status": "drafted"}

    def _render_reel(self, state: WeekState) -> dict[str, str]:
        """FR-06: opt-in offline rendering before checks; never creates approvals."""
        if self.video_studio is None:
            return {"status": "drafted"}
        brand = self.repository.brand(state["brand_hash"])
        for slot in self.repository.slots(state["run_id"]):
            post = self.repository.post(slot.id)
            if post.format != "reel" or post.render_artifact is not None:
                continue
            recipe = self.render_recipes.get(slot.id)
            if recipe is None and self.video_catalog is not None:
                from instabay.video.backends.editorial import EditorialVideoBackend

                if not isinstance(self.video_studio.backend, EditorialVideoBackend):
                    raise ValueError("The directed board requires the editorial assembler")
                board = VideoDirector(self.service).direct(slot.id, post.brief, self.video_catalog)
                recipe = editorial_recipe(
                    board,
                    self.video_studio.root,
                    self.video_studio.root / "outputs/video-boards" / slot.id,
                    "en",
                    animatic=self.allow_video_animatic and state["demo"],
                )
            elif recipe is None:
                if not state["demo"] or self.video_studio.backend.name != "stub":
                    raise ValueError(
                        "HUMAN: supply an exact approved native recipe before GPU work"
                    )
                shots = BriefWriter(self.service).shot_list(
                    slot, brand, post.brief, self.approved_stills
                )
                recipe = stub_recipe(shots, self.video_studio.root)
            elif recipe.shots.reel_id != slot.id:
                raise ValueError("Recipe belongs to a different reel slot")
            result = self.video_studio.render(recipe)
            attachment = RenderAttachment.model_validate(
                {
                    "recipe_hash": result.recipe_hash,
                    "render_recipe": recipe.model_dump(mode="json"),
                    "file": result.file,
                    "file_sha256": result.file_sha256,
                    "contact_sheet": result.contact_sheet,
                    "contact_sha256": result.contact_sha256,
                    "qa_status": result.qa.status,
                    "generated": result.ai_disclosure,
                    "reference_only": result.reference_only,
                }
            )
            self.repository.save_post(
                Post.model_validate(
                    post.model_dump()
                    | {
                        "media_path": result.file,
                        "media_status": "rendered",
                        "render_artifact": attachment,
                        "ai_disclosure": result.ai_disclosure,
                        "prompt_hashes": post.prompt_hashes
                        | prompt_hashes(
                            self.service, ["video_director" if self.video_catalog else "shot_list"]
                        ),
                    }
                )
            )
        return {"status": "drafted"}

    def _checks(self, state: WeekState) -> dict[str, str]:
        brand = self.repository.brand(state["brand_hash"])
        judge = CheckCascade(
            Judge(self.service),
            self.decision_engine,
            self.calibration,
            allow_synthetic=state["demo"] and self.allow_synthetic_decisions,
        )
        for slot in self.repository.slots(state["run_id"]):
            post = self.repository.post(slot.id)
            try:
                existing = self.repository.review(post.id)
            except ValueError:
                existing = None
            if existing is None or (
                post.revision == 0
                and (
                    not existing.rules.passed
                    or (existing.judge is not None and not existing.judge.passed)
                )
            ):
                checked, review = judge.check_and_refine(
                    post, slot, brand, record_initial=self.repository.save_review
                )
                self.repository.save_post(checked)
                self.repository.save_review(review)
        return {"status": "checked"}

    def _human_approval(self, state: WeekState) -> dict[str, str]:
        # The resume payload carries no approvals; only append-only DB rows authorize publishing.
        interrupt(
            {"kind": "human_approval", "run_id": state["run_id"], "post_ids": state["post_ids"]}
        )
        for post_id in state["post_ids"]:
            post = self.repository.post(post_id)
            decision = self.repository.latest_approval(post_id)
            if decision is None or decision.content_hash != post.content_hash:
                raise ApprovalPendingError("Some posts still need current stored human decisions")
        return {"status": "checked"}

    def _publish(self, state: WeekState) -> dict[str, str]:
        for post_id in state["post_ids"]:
            approval = self.repository.latest_approval(post_id)
            if approval and approval.decision in {"APPROVED", "EDITED"}:
                self.publisher.publish(post_id)
        return {"status": "completed"}

    def result(self, run_id: str) -> WorkflowResult:
        """FR-09: validate the checkpoint before returning a human-facing status."""
        snapshot = self.graph.get_state(self._config(run_id))
        if not snapshot.values:
            raise KeyError("Unknown checkpoint run")
        state = TypeAdapter(WeekState).validate_python(snapshot.values)
        return WorkflowResult(
            run_id=state["run_id"],
            post_ids=state["post_ids"],
            status=(
                "approval_pending"
                if snapshot.next == ("human_approval",)
                else "in_progress"
                if snapshot.next
                else "completed"
            ),
        )

    def start(self, request: WorkflowInput) -> WorkflowResult:
        """FR-09: starting the same thread again returns its existing checkpoint."""
        config = self._config(request.run_id)
        self.service.run_id = request.run_id
        history = [
            row
            for row in self.calls.calls()
            if row.run_id == request.run_id and row.status != "cached"
        ]
        self.service.usage = RunUsage(
            calls=len(history),
            tokens=sum(row.input_tokens + row.output_tokens for row in history),
            cost_usd=sum(row.cost_usd for row in history),
        )
        if self.graph.get_state(config).values:
            stored = self.repository.run(request.run_id)
            if stored != request:
                raise ValueError("Run ID already belongs to different inputs")
            snapshot = self.graph.get_state(config)
            if snapshot.next and snapshot.next != ("human_approval",):
                with tracing_context(enabled=False):
                    self.graph.invoke(None, config)
            return self.result(request.run_id)
        state: WeekState = {
            "run_id": request.run_id,
            "week_start": request.week_start.isoformat(),
            "demo": request.demo,
            "brand_hash": "",
            "post_ids": [],
            "status": "planned",
        }
        with tracing_context(enabled=False):
            self.graph.invoke(state, config)
        return self.result(request.run_id)

    def resume(self, run_id: str) -> WorkflowResult:
        """FR-09: check all stored decisions before consuming the graph interrupt."""
        current = self.result(run_id)
        if current.status == "completed":
            return current
        snapshot = self.graph.get_state(self._config(run_id))
        if current.status == "in_progress" and snapshot.next != ("publish",):
            raise ApprovalPendingError(
                "Generation is incomplete; rerun demo to continue its checkpoint"
            )
        for post_id in current.post_ids:
            post = self.repository.post(post_id)
            decision = self.repository.latest_approval(post_id)
            if decision is None or decision.content_hash != post.content_hash:
                raise ApprovalPendingError("Stored human decisions are still pending")
        with tracing_context(enabled=False):
            if current.status == "in_progress":
                self.graph.invoke(None, self._config(run_id))
            else:
                self.graph.invoke(Command(resume="read_stored_decisions"), self._config(run_id))
        return self.result(run_id)

    def close(self) -> None:
        """NFR-06: release checkpoint, call-ledger and business database resources."""
        self._stack.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
