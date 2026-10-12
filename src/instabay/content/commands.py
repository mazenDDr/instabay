"""FR-04 to FR-09: render an evidence-bound mixed week, then stop at stored human approval."""

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console

from instabay.adapters.audited_llm import AuditedLLMClient
from instabay.adapters.native_llm import NativeLLMClient
from instabay.approval import show_post
from instabay.content.evidence import ContentEvidence
from instabay.content.export import export_gallery
from instabay.core.schemas import BrandConstitution, BrandInput, WorkflowInput
from instabay.graph import WeekRunner
from instabay.llm import RunBudget
from instabay.settings import Settings
from instabay.video.backends.editorial import EditorialVideoBackend
from instabay.video.direction import ObjectCatalog
from instabay.video.studio import VideoStudio

TEMPLATES = ["visual_brief", "grounded_copy_en", "grounded_copy_ar", "video_director"]


def register_content_commands(app: typer.Typer) -> None:
    """FR-09: a creative preview is not a publishing command or an approval."""

    @app.command("reference-week")
    def reference_week(
        evidence: Annotated[Path, typer.Option()] = Path("config/reethi-faru-evidence.yaml"),
        brand: Annotated[Path, typer.Option()] = Path("config/reference-campaign-brand.yaml"),
        scenes: Annotated[Path | None, typer.Option()] = None,
        output: Annotated[Path, typer.Option()] = Path("outputs/reference-week"),
        week_start: Annotated[str, typer.Option()] = "2026-10-12",
        run_id: Annotated[str, typer.Option()] = "reference-w42",
        model: Annotated[str | None, typer.Option()] = None,
        origin: Annotated[str, typer.Option()] = "http://127.0.0.1:18765",
        confirm_generation: Annotated[bool, typer.Option()] = False,
        render_reels: Annotated[bool, typer.Option()] = False,
        animatic: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """FR-04: preview a complete pillar-aligned week of photos, carousels and scenic reels."""
        if Settings.from_env().mode != "dry_run":
            raise typer.BadParameter("Reference studies require INSTABAY_MODE=dry_run")
        root = Path.cwd().resolve()
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        proof = ContentEvidence.model_validate(yaml.safe_load(evidence.read_text()))
        draft_brand = BrandConstitution.model_validate(yaml.safe_load(brand.read_text()))
        catalog = proof.objects(root)
        if scenes:
            supplied = ObjectCatalog.model_validate(yaml.safe_load(scenes.read_text()))
            old = catalog.model_dump(exclude={"objects": {"__all__": {"clip"}}})
            new = supplied.model_dump(exclude={"objects": {"__all__": {"clip"}}})
            if old != new:
                raise typer.BadParameter("Motion catalog changed the verified source scenes")
            catalog = supplied
        if model and not confirm_generation:
            raise typer.BadParameter("Native drafting requires --confirm-generation")
        client = NativeLLMClient(origin, model, confirm_external=True) if model else None
        try:
            with WeekRunner(
                output / "posts.sqlite",
                output / "checkpoints.sqlite",
                output / "outbox",
                BrandInput(brief=draft_brand.positioning, owner_answers={}),
                content_evidence=proof,
                content_root=root,
                reference_brand=draft_brand,
                video_catalog=catalog,
                video_studio=VideoStudio(
                    output / "posts.sqlite", root, output / "renders", EditorialVideoBackend()
                )
                if render_reels
                else None,
                allow_video_animatic=animatic,
                llm_client=AuditedLLMClient(client, output / "native-calls") if client else None,
                model_overrides={t: model for t in TEMPLATES} if model else {},
                token_overrides={
                    "visual_brief": 1200,
                    "grounded_copy_en": 700,
                    "grounded_copy_ar": 800,
                    "video_director": 1700,
                },
                run_budget=RunBudget(max_calls=70, max_tokens=200000),
            ) as runner:
                result = runner.start(
                    WorkflowInput(
                        run_id=run_id, week_start=date.fromisoformat(week_start), demo=True
                    )
                )
                posts = [runner.repository.post(i) for i in result.post_ids]
                data = {
                    "run": result.model_dump(mode="json"),
                    "synthetic": model is None,
                    "usage": runner.service.usage.model_dump(),
                    "posts": [p.model_dump(mode="json") for p in posts],
                    "reviews": [
                        runner.repository.review(p.id).model_dump(mode="json") for p in posts
                    ],
                    "post_approved": False,
                    "published": False,
                }
                (output / "campaign.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n"
                )
                page = export_gallery(
                    posts,
                    {s.id: s.arm.pillar for s in runner.repository.slots(run_id)},
                    root,
                    output / "review",
                    synthetic=model is None,
                )
                typer.echo(f"Review gallery: {page}")
                for post in posts:
                    show_post(runner.repository, post.id, Console())
                typer.echo(f"{result.status}: {len(posts)} posts; source study, nothing published.")
        finally:
            if client:
                client.close()
