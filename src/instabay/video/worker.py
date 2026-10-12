"""FR-06, NFR-06: durable idempotent render queue; one claim at a time."""

import sqlite3
from typing import Literal

from instabay.core.recipe import RenderRecipe
from instabay.core.schemas import Boundary, Hash
from instabay.video.studio import VideoStudio


class JobStatus(Boundary):
    """FR-06: failed/interrupted jobs remain visible, never silently retried."""

    id: Hash
    status: Literal["queued", "running", "complete", "failed"]
    artifact_urls: list[str]
    error: str | None = None


class RenderQueue:
    """NFR-03: SQLite claim lock plus VideoStudio's process-wide rendering lock."""

    def __init__(self, studio: VideoStudio) -> None:
        self.studio = studio
        with sqlite3.connect(studio.db, timeout=30) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS worker_job (id TEXT PRIMARY KEY,"
                "recipe_json TEXT NOT NULL,status TEXT NOT NULL,error TEXT)"
            )

    def submit(self, recipe: RenderRecipe) -> JobStatus:
        """FR-06: repeated submission returns the stored job, even after process restart."""
        with sqlite3.connect(self.studio.db, timeout=30) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO worker_job VALUES (?,?,?,NULL)",
                (recipe.recipe_hash, recipe.model_dump_json(), "queued"),
            )
        return self.status(recipe.recipe_hash)

    def status(self, job_id: str) -> JobStatus:
        """NFR-04: only known exact hashes expose artifact URLs."""
        with sqlite3.connect(self.studio.db) as connection:
            row = connection.execute(
                "SELECT status,error FROM worker_job WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Unknown render job")
        return JobStatus(
            id=job_id,
            status=row[0],
            error=row[1],
            artifact_urls=[
                f"/jobs/{job_id}/artifacts/{name}"
                for name in ("reel.mp4", "contact-sheet.jpg", "recipe.json", "result.json")
            ]
            if row[0] == "complete"
            else [],
        )

    def run_once(self) -> bool:
        """FR-06: HUMAN: run on gpu-box; crashed claims are held for reconciliation."""
        with sqlite3.connect(self.studio.db, timeout=30) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM worker_job WHERE status='running'").fetchone():
                return False
            if connection.execute(
                "SELECT 1 FROM worker_job WHERE status='failed' "
                "AND json_extract(recipe_json,'$.backend') != 'stub'"
            ).fetchone():
                return False
            row = connection.execute(
                "SELECT id,recipe_json FROM worker_job WHERE status='queued' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            connection.execute("UPDATE worker_job SET status='running' WHERE id=?", (row[0],))
        try:
            recipe = RenderRecipe.model_validate_json(row[1])
            self.studio.render(recipe)
        except Exception:
            error: str | None
            status, error = (
                "failed",
                "Render failed; inspect private artifacts and reconcile before retry",
            )
        else:
            status, error = "complete", None
        with sqlite3.connect(self.studio.db, timeout=30) as connection:
            connection.execute(
                "UPDATE worker_job SET status=?,error=? WHERE id=?", (status, error, row[0])
            )
        return True
