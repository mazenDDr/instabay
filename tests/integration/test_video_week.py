"""FR-06, FR-09: real render node remains before checks and the human approval interrupt."""

from datetime import date
from pathlib import Path

import pytest

from instabay.core.schemas import ApprovalRequest, WorkflowInput
from instabay.graph import ApprovalPendingError, WeekRunner
from instabay.video.studio import VideoStudio
from tests.integration.test_week import inputs
from tests.unit.test_video_recipe import ROOT, shotlist


def test_rendered_week_approval_persistence_and_disclosure(tmp_path: Path) -> None:
    db = tmp_path / "week.sqlite"
    checkpoints = tmp_path / "checkpoints.sqlite"
    out = tmp_path / "out"
    studio = VideoStudio(db, ROOT, tmp_path / "renders")
    with WeekRunner(
        db,
        checkpoints,
        out,
        inputs(),
        video_studio=studio,
        approved_stills=[shotlist().shots[0].keyframe],
    ) as runner:
        result = runner.start(WorkflowInput(run_id="2026-w42", week_start=date(2026, 10, 12)))
        assert result.status == "approval_pending" and not out.exists()
        rendered = []
        for post_id in result.post_ids:
            post = runner.repository.post(post_id)
            if post.format == "reel":
                rendered.append(post)
                assert post.media_status == "rendered" and post.render_artifact
                assert Path(post.render_artifact.contact_sheet).exists()
                assert runner.repository.review(post_id).flagged
                assert any("Video QA pending" in f for f in runner.repository.review(post_id).flags)
                # Force generated still provenance to verify disclosure binding on both captions.
                data = post.model_dump()
                recipe = data["render_artifact"]["render_recipe"]
                for shot in recipe["shots"]["shots"]:
                    shot["keyframe"].update(source="generated", prompt="abstract light", seed=7)
                from instabay.core.recipe import RenderRecipe

                data["render_artifact"].update(
                    recipe_hash=RenderRecipe.model_validate(recipe).recipe_hash, generated=True
                )
                data["ai_disclosure"] = True
                from instabay.core.schemas import Post

                disclosed = Post.model_validate(data)
                assert "Scenes created with AI" in disclosed.full_caption("en")
                assert "بالذكاء الاصطناعي" in disclosed.full_caption("ar")
        assert rendered
        with pytest.raises(ApprovalPendingError):
            runner.resume("2026-w42")
        for post_id in result.post_ids:
            runner.repository.approve(
                post_id,
                ApprovalRequest(
                    decision="APPROVED",
                    actor="synthetic-test-human",
                    reason="Offline fixture gate only; flagged media is reference-only",
                    seconds_spent=1,
                ),
            )
    with WeekRunner(db, checkpoints, out, inputs()) as restarted:
        assert restarted.resume("2026-w42").status == "completed"
        assert len(restarted.repository.publications("2026-w42")) == 7
