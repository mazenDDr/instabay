"""FR-01, FR-04, FR-09: non-demo generation under a stored frozen brand; no live calls."""

import hashlib
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

from instabay.adapters.llm import LLMClient
from instabay.content.evidence import ContentEvidence
from instabay.content.export import export_gallery
from instabay.core.schemas import (
    BrandConstitution,
    BrandInput,
    Cadence,
    Slot,
    WorkflowInput,
    WorkflowResult,
    canonical_hash,
)
from instabay.graph import WeekRunner
from instabay.llm import RunBudget
from instabay.repository import Repository
from instabay.video.backends.editorial import EditorialVideoBackend
from instabay.video.direction import ObjectCatalog
from instabay.video.files import local_file
from instabay.video.studio import VideoStudio

TEMPLATES = ("visual_brief", "grounded_copy_en", "grounded_copy_ar", "video_director")


def generate_week(
    *,
    brand: BrandConstitution,
    evidence: ContentEvidence,
    catalog: ObjectCatalog,
    root: Path,
    output: Path,
    run_id: str,
    week_start: date,
    model: str,
    client: LLMClient,
    budget: RunBudget,
    replay: bool = False,
    draft_only: bool = False,
    cadence: Cadence | None = None,
    asset_pools: Callable[[list[Slot]], dict[str, list[str]]] | None = None,
) -> WorkflowResult:
    """FR-09: draft/review only; approval and Instagram are separate explicit actions."""
    root, output = root.resolve(), output.resolve()
    digest = canonical_hash(brand)
    repo = Repository(output / "posts.sqlite")
    try:
        if repo.frozen_brand(digest) != brand:
            raise ValueError("Stored brand differs from the supplied constitution")
    finally:
        repo.close()
    original = evidence.objects(root)
    omit = {"objects": {"__all__": {"clip", "conditioning"}}}
    if original.model_dump(exclude=omit) != catalog.model_dump(exclude=omit):
        raise ValueError("Motion catalog changed the approved photo sources")
    if set(evidence.pillar_guidance) != {p.id for p in brand.pillars}:
        raise ValueError("Every brand pillar needs source-backed direction")
    if not draft_only:
        for obj in catalog.objects:
            if obj.clip is None:
                raise ValueError("Animate source photos first, or request --draft-only")
            local_file(root, obj.clip)
            if obj.clip.motion_recipe:
                local_file(root, obj.clip.motion_recipe)
    prompts = Path(__file__).parents[1] / "prompts"
    manifest = {
        "run_id": run_id,
        "week_start": week_start.isoformat(),
        "brand_hash": digest,
        "evidence_hash": canonical_hash(evidence),
        "catalog_hash": canonical_hash(catalog),
        "model": model,
        "draft_only": draft_only,
        **({"cadence": cadence.model_dump(mode="json")} if cadence else {}),
        "prompt_hashes": {
            t: hashlib.sha256((prompts / f"{t}.md").read_bytes()).hexdigest() for t in TEMPLATES
        },
    }
    file = output / "run-manifest.json"
    if file.exists() and json.loads(file.read_text()) != manifest:
        raise ValueError("Run inputs changed; use a new run ID and output directory")
    output.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with WeekRunner(
        output / "posts.sqlite",
        output / "checkpoints.sqlite",
        output / "outbox",
        BrandInput(brief="Stored frozen constitution", owner_answers={}),
        frozen_brand_hash=digest,
        llm_client=client,
        model_overrides={t: model for t in TEMPLATES},
        token_overrides={
            "visual_brief": 1200,
            "grounded_copy_en": 700,
            "grounded_copy_ar": 800,
            "video_director": 1700,
        },
        run_budget=budget,
        cadence=cadence,
        asset_pools=asset_pools,
        content_evidence=evidence,
        content_root=root,
        video_catalog=catalog,
        video_studio=None
        if draft_only
        else VideoStudio(
            output / "posts.sqlite", root, output / "renders", EditorialVideoBackend()
        ),
    ) as runner:
        result = runner.start(WorkflowInput(run_id=run_id, week_start=week_start, demo=False))
        posts = [runner.repository.post(i) for i in result.post_ids]
        data = {
            "run": result.model_dump(mode="json"),
            "generation_mode": "recorded_replay" if replay else "native",
            "usage": runner.service.usage.model_dump(),
            "posts": [p.model_dump(mode="json") for p in posts],
            "reviews": [runner.repository.review(p.id).model_dump(mode="json") for p in posts],
            "post_approved": False,
            "published": False,
            "asset_pools": asset_pools(runner.repository.slots(run_id)) if asset_pools else None,
        }
        (output / "campaign.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        export_gallery(
            posts,
            {s.id: s.arm.pillar for s in runner.repository.slots(run_id)},
            root,
            output / "review",
            synthetic=False,
        )
    return result
