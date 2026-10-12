"""FR-09, FR-12, FR-13: multi-week loop with a fresh human approval gate every week."""

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from instabay.adapters.fake_llm import FakeLLMMissingFixture, FixtureCatalog
from instabay.adapters.fixture_fidelity import FixtureFidelity
from instabay.adapters.insights import SimulatedInsights
from instabay.agents.analyst import Analyst
from instabay.agents.brand_architect import BrandArchitect
from instabay.core.learning import WeekAnalysis
from instabay.core.optimizer import ThompsonOptimizer
from instabay.core.schemas import (
    Boundary,
    BrandInput,
    Identifier,
    WorkflowInput,
    canonical_hash,
)
from instabay.graph import ApprovalPendingError, WeekRunner
from sim.world import AudienceWorld, WorldConfig


class CycleInput(Boundary):
    """NFR-03: a cycle's identity, seed and dates are immutable after its first invocation."""

    id: Identifier = "cycle"
    weeks: int = Field(default=3, ge=1)
    seed: int = Field(default=7, ge=0)
    week_start: date = date(2026, 10, 12)

    @model_validator(mode="after")
    def monday(self) -> Self:
        if self.week_start.weekday() != 0:
            raise ValueError("Cycles must start on Monday")
        return self


class CycleResult(Boundary):
    """FR-09: completed reports plus the one current approval queue, never fake approvals."""

    cycle_id: Identifier
    status: Literal["approval_pending", "completed"]
    current_run_id: Identifier | None = None
    reports: list[WeekAnalysis]


class CycleRunner:
    """FR-13: serialized weekly planning → approval → export → metrics → learning."""

    def __init__(
        self,
        db: Path,
        checkpoints: Path,
        outbox: Path,
        brand_input: BrandInput,
        fixtures: Path = Path("tests/fixtures/llm"),
    ) -> None:
        self.db, self.checkpoints, self.outbox = db, checkpoints, outbox
        self.brand_input, self.fixtures = brand_input, fixtures

    def run(self, request: CycleInput) -> CycleResult:
        """FR-09: resume approved weeks; stop immediately when any current decision is missing."""
        catalog_path = self.fixtures / "cycle-catalog.json"
        catalog = FixtureCatalog.model_validate_json(catalog_path.read_bytes())
        # Validate coverage before creating any cycle state. Larger packs can be authored offline.
        for week in range(1, request.weeks + 1):
            for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
                for template in (
                    "brief_writer",
                    "copy_en",
                    "copy_ar",
                    "judge",
                    "fidelity",
                    "copy_en_revision",
                    "copy_ar_revision",
                ):
                    key = f"{template}__{request.id}-w{week:02d}-{day}-1"
                    if key not in catalog.entries:
                        raise FakeLLMMissingFixture(f"Cycle pack has no recorded key: {key}")
        fixture_hash = hashlib.sha256(
            catalog_path.read_bytes()
            + (self.fixtures / "brand_architect__brand-draft.json").read_bytes()
        ).hexdigest()
        world_config = WorldConfig()
        config: dict[str, object] = {
            **request.model_dump(mode="json"),
            "brand_inputs_hash": canonical_hash(self.brand_input),
            "fixture_hash": fixture_hash,
            "world": world_config.model_dump(mode="json"),
            "optimizer": "factored-thompson-v1-beta-1-1-pseudo-20",
        }
        reports: list[WeekAnalysis] = []
        for index in range(request.weeks):
            run_id = f"{request.id}-w{index + 1:02d}"
            with WeekRunner(
                self.db, self.checkpoints, self.outbox, self.brand_input, self.fixtures
            ) as runner:
                runner.repository.register_cycle(request.id, config)
                runner.service.run_id = run_id
                brand = BrandArchitect(runner.service).draft(self.brand_input)
                digest = canonical_hash(brand)
                scope = canonical_hash(
                    {
                        "brand_hash": digest,
                        "world_seed": request.seed,
                        "world": world_config.model_dump(),
                    }
                )
                runner.preferences = ThompsonOptimizer(request.seed).preferences(
                    brand, runner.repository.posteriors(scope), run_id
                )
                result = runner.start(
                    WorkflowInput(
                        run_id=run_id,
                        week_start=request.week_start + timedelta(weeks=index),
                        demo=True,
                    )
                )
                if result.status == "approval_pending":
                    try:
                        result = runner.resume(run_id)
                    except ApprovalPendingError:
                        return CycleResult(
                            cycle_id=request.id,
                            status="approval_pending",
                            current_run_id=run_id,
                            reports=reports,
                        )
                if result.status != "completed":
                    raise RuntimeError("Weekly generation is incomplete; rerun the same cycle")
                reports.append(
                    Analyst(
                        runner.repository,
                        SimulatedInsights(AudienceWorld(request.seed, world_config)),
                        FixtureFidelity(catalog),
                        scope,
                    ).analyze(run_id)
                )
        return CycleResult(cycle_id=request.id, status="completed", reports=reports)
