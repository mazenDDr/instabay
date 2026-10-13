"""FR-04, FR-09: the owner's rejection reasons and caption edits, fed back to the writers.

No model is retrained. Recent lessons are added to the brief and caption writers' inputs as
"avoid" (why posts were rejected) and "prefer" (how the owner rewrote captions) notes. Only the
latest decision per post counts, so an undone rejection is no longer a lesson.
"""

import json
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import Field

from instabay.core.schemas import Boundary, canonical_hash

LIMIT = 8


class Lesson(Boundary):
    id: str
    kind: Literal["rejected", "edited"]
    language: Literal["en", "ar", "both"]
    text: str = Field(max_length=600)
    example: str = Field(default="", max_length=200)
    pillar: str | None = None
    format: str | None = None
    at: str
    run: str


class OwnerFeedback(Boundary):
    """FR-04: what the writers see; empty lists mean no lessons yet."""

    avoid: list[str] = Field(default_factory=list)
    prefer_en: list[str] = Field(default_factory=list)
    prefer_ar: list[str] = Field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.avoid or self.prefer_en or self.prefer_ar)

    def for_language(self, language: Literal["en", "ar"]) -> dict[str, list[str]]:
        return {
            "avoid": self.avoid,
            "prefer": self.prefer_en if language == "en" else self.prefer_ar,
        }


def _changes(diff: str) -> list[tuple[str, str]]:
    """Pair removed and added lines of a unified diff as (before, after)."""
    removed = [
        ln[1:].strip()
        for ln in diff.splitlines()
        if ln.startswith("-") and not ln.startswith("---")
    ]
    added = [
        ln[1:].strip()
        for ln in diff.splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    ]
    pairs = [(b, a) for b, a in zip(removed, added, strict=False) if b != a]
    pairs += [("", a) for a in added[len(removed) :]]
    return [(b[:200], a[:200]) for b, a in pairs if a or b]


def collect(dbs: list[Path], forgotten: set[str] | None = None, limit: int = LIMIT) -> list[Lesson]:
    """FR-09: newest lessons first, from every run database the studio can see."""
    lessons: list[Lesson] = []
    for path in dbs:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
                if not {"approval", "post", "slot", "arm"} <= tables:
                    continue
                rows = db.execute(
                    "SELECT a.*, p.en_caption, p.brief_json, ar.pillar, ar.format, s.run_id "
                    "FROM approval a JOIN post p ON a.post_id = p.id "
                    "JOIN slot s ON p.slot_id = s.id JOIN arm ar ON s.arm_id = ar.id "
                    "WHERE a.sequence IN (SELECT MAX(sequence) FROM approval GROUP BY post_id) "
                    "AND a.decision IN ('REJECTED', 'EDITED')"
                ).fetchall()
        except sqlite3.Error:
            continue
        for r in rows:
            hook = str(json.loads(r["brief_json"]).get("hook", ""))[:200]
            base = {
                "pillar": r["pillar"],
                "format": r["format"],
                "at": r["decided_at"],
                "run": r["run_id"],
            }
            if r["decision"] == "REJECTED" and r["reason"].strip():
                text = r["reason"].strip()[:600]
                lessons.append(
                    Lesson(
                        id=canonical_hash({"post": r["post_id"], "approval": r["id"]})[:16],
                        kind="rejected",
                        language="both",
                        text=text,
                        example=hook,
                        **base,
                    )
                )
            elif r["decision"] == "EDITED":
                for key, diff in json.loads(r["diff_json"] or "{}").items():
                    language: Literal["en", "ar"] = "ar" if key.startswith("ar") else "en"
                    for before, after in _changes(diff):
                        lessons.append(
                            Lesson(
                                id=canonical_hash({"approval": r["id"], "b": before, "a": after})[
                                    :16
                                ],
                                kind="edited",
                                language=language,
                                text=f"“{before}” → “{after}”" if before else f"added “{after}”",
                                example=hook,
                                **base,
                            )
                        )
    lessons = [x for x in lessons if x.id not in (forgotten or set())]
    lessons.sort(key=lambda x: x.at, reverse=True)
    return lessons[: limit * 3]


def for_writers(lessons: list[Lesson], limit: int = LIMIT) -> OwnerFeedback:
    """FR-04: at most `limit` notes per list, newest first."""
    avoid = [
        f"Rejected a {x.format or 'post'} ({x.pillar or 'any pillar'}): {x.text}"
        for x in lessons
        if x.kind == "rejected"
    ][:limit]
    prefer_en = [x.text for x in lessons if x.kind == "edited" and x.language == "en"][:limit]
    prefer_ar = [x.text for x in lessons if x.kind == "edited" and x.language == "ar"][:limit]
    return OwnerFeedback(avoid=avoid, prefer_en=prefer_en, prefer_ar=prefer_ar)
