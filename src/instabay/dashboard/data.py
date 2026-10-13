"""FR-09, FR-11: read-only views over every run database, plus the owner's approval action."""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from pydantic import JsonValue

from instabay.core.schemas import ApprovalRequest
from instabay.repository import Repository

METRICS = ("reach", "views", "likes", "comments", "saved", "shares", "engagement_rate")


def discover(runs: Path) -> list[Path]:
    """FR-11: run databases up to three folders deep under the runs root."""
    found: list[Path] = []
    for pattern in ("*.sqlite", "*.sqlite3", "*/*.sqlite", "*/*.sqlite3", "*/*/*.sqlite"):
        found.extend(runs.glob(pattern))
    result = []
    for path in sorted(set(found)):
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
        except sqlite3.Error:
            continue
        if {"workflow_run", "post", "slot", "arm"} <= tables:
            result.append(path)
    return result


def _media(raw: str | None, media_path: str | None, root: Path) -> list[str]:
    files = [f["file"] for f in json.loads(raw).get("files", [])] if raw else []
    files = files or ([media_path] if media_path else [])
    urls = []
    for file in files:
        path = Path(file) if Path(file).is_absolute() else root / file
        if path.resolve().is_relative_to(root) and path.is_file():
            urls.append("/media/run?path=" + path.resolve().relative_to(root).as_posix())
    return urls


def run_posts(db_path: Path, root: Path) -> dict[str, list[dict[str, JsonValue]]]:
    """FR-09, FR-11: posts grouped by run with review, approval, publication and metrics."""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
        decisions = (
            {
                r["post_id"]: r["decision"]
                for r in db.execute(
                    "SELECT post_id, decision FROM approval WHERE sequence IN "
                    "(SELECT MAX(sequence) FROM approval GROUP BY post_id)"
                )
            }
            if "approval" in tables
            else {}
        )
        published = (
            {r[0] for r in db.execute("SELECT post_id FROM publication")}
            if "publication" in tables
            else set()
        )
        reviews = (
            {r["post_id"]: r for r in db.execute("SELECT post_id, flags_json FROM review")}
            if "review" in tables
            else {}
        )
        metrics: dict[str, dict[str, float]] = defaultdict(dict)
        sources: dict[str, str] = {}
        if "metric" in tables:
            for r in db.execute(
                "SELECT post_id, name, value, source FROM metric m WHERE observed_at = "
                "(SELECT MAX(observed_at) FROM metric WHERE post_id = m.post_id AND name = m.name)"
            ):
                metrics[r["post_id"]][r["name"]] = r["value"]
                sources[r["post_id"]] = r["source"]
        runs: dict[str, list[dict[str, JsonValue]]] = defaultdict(list)
        for r in db.execute(
            "SELECT p.*, s.run_id, s.scheduled_at, a.pillar, a.format FROM post p "
            "JOIN slot s ON p.slot_id = s.id JOIN arm a ON s.arm_id = a.id "
            "ORDER BY s.scheduled_at"
        ):
            columns = r.keys()
            review = reviews.get(r["id"])
            flags = json.loads(review["flags_json"]) if review else []
            runs[r["run_id"]].append(
                {
                    "id": r["id"],
                    "format": r["format"],
                    "pillar": r["pillar"],
                    "scheduled_at": r["scheduled_at"],
                    "hook": json.loads(r["brief_json"]).get("hook", ""),
                    "caption_en": r["en_caption"],
                    "caption_ar": r["ar_caption"],
                    "ai_disclosure": bool(r["ai_disclosure"]),
                    "media": _media(
                        r["photo_json"] if "photo_json" in columns else None,
                        r["media_path"],
                        root,
                    ),  # type: ignore[dict-item]
                    "flags": flags,
                    "decision": None
                    if decisions.get(r["id"]) == "REVOKED"
                    else decisions.get(r["id"]),
                    "published": r["id"] in published,
                    "metrics": metrics.get(r["id"], {}),  # type: ignore[dict-item]
                    "metric_source": sources.get(r["id"]),
                }
            )
    return dict(runs)


def summaries(dbs: list[Path], root: Path) -> list[dict[str, JsonValue]]:
    """FR-11: one row per (database, run), newest first."""
    rows: list[dict[str, JsonValue]] = []
    for path in dbs:
        try:
            grouped = run_posts(path, root)
        except (sqlite3.Error, ValueError, KeyError, IndexError):
            continue
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            meta = {r[0]: (r[1], bool(r[2])) for r in db.execute("SELECT * FROM workflow_run")}
        for run_id, posts in grouped.items():
            week, demo = meta.get(run_id, ("", False))
            rows.append(
                {
                    "key": f"{path.relative_to(root).as_posix()}::{run_id}",
                    "db": path.relative_to(root).as_posix(),
                    "run_id": run_id,
                    "week_start": week,
                    "demo": demo,
                    "posts": posts,  # type: ignore[dict-item]
                }
            )
    rows.sort(key=lambda r: (str(r["week_start"]), str(r["key"])), reverse=True)
    return rows


def decide(db_path: Path, post_id: str, request: ApprovalRequest) -> str:
    """FR-09: the owner's click is stored exactly like the CLI approval (hash-bound)."""
    repository = Repository(db_path)
    try:
        return repository.approve(post_id, request).decision
    finally:
        repository.close()


def used_media(dbs: list[Path]) -> set[str]:
    """FR-04: library photo IDs that any generated post still references."""
    used: set[str] = set()
    for path in dbs:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            columns = {r[1] for r in db.execute("PRAGMA table_info(post)")}
            if "evidence_json" not in columns:
                continue
            for (raw,) in db.execute(
                "SELECT evidence_json FROM post WHERE evidence_json IS NOT NULL"
            ):
                selection = json.loads(raw).get("context", {}).get("selection", {})
                used.update(selection.get("media_ids", []))
    return used
