"""FR-01, FR-04, NFR-03: content-addressed owner photos and generated views in one SQLite file."""

import hashlib
import io
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field, JsonValue, model_validator

from instabay.core.schemas import Boundary, Hash, Identifier

Origin = Literal["owner", "generated"]
MAX_UPLOAD_BYTES = 25_000_000
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
VIEW_OK = 0.8  # min(same_place, photoreal); separated 6 good / 5 bad views by eye, n=12 (ADR 0013)
CONFIDENT = 0.5  # provisional: top-pillar probability; re-tune from owner labels (ADR 0013)

SCHEMA = """
CREATE TABLE IF NOT EXISTS asset (
  id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  file TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  origin TEXT NOT NULL,
  parent_id TEXT REFERENCES asset(id),
  note_en TEXT NOT NULL DEFAULT '',
  note_ar TEXT NOT NULL DEFAULT '',
  added_by TEXT NOT NULL,
  rights_confirmed INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  model_pillar TEXT,
  model_confidence REAL,
  people REAL,
  owner_pillar TEXT,
  approved INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,
  recipe_json TEXT,
  fidelity_json TEXT,
  vlm_pillar TEXT,
  vlm_reason TEXT,
  note_source TEXT
);
CREATE TABLE IF NOT EXISTS classification (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL REFERENCES asset(id),
  engine_id TEXT NOT NULL,
  synthetic INTEGER NOT NULL,
  questions_hash TEXT NOT NULL,
  answers_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS setting (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  undo_json TEXT,
  undone INTEGER NOT NULL DEFAULT 0
);
"""
# Owner-editable asset fields an activity entry can restore.
UNDOABLE = ("owner_pillar", "note_en", "note_ar", "approved", "rejected", "deleted_at")


NEAR_COPY = 64  # dHash bits of 256: shots ~30 from their source looked identical (2026-10-13)


def dhash(path: Path, size: int = 16) -> list[bool]:
    """FR-06: perceptual gradient hash; small distances mean the same picture."""
    with Image.open(path) as image:
        gray = ImageOps.exif_transpose(image).convert("L").resize((size + 1, size))
        px = list(gray.tobytes())
    return [
        px[r * (size + 1) + c] > px[r * (size + 1) + c + 1]
        for r in range(size)
        for c in range(size)
    ]


def distance(a: Path, b: Path) -> int:
    return sum(x != y for x, y in zip(dhash(a), dhash(b), strict=True))


def now() -> str:
    return datetime.now(UTC).isoformat()


class Asset(Boundary):
    """FR-04: one exact image; an owner label always outranks the classifier."""

    id: Identifier
    sha256: Hash
    file: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    origin: Origin
    parent_id: str | None = None
    note_en: str = ""
    note_ar: str = ""
    added_by: str
    rights_confirmed: bool
    created_at: str
    model_pillar: str | None = None
    model_confidence: float | None = None
    people: float | None = None
    owner_pillar: str | None = None
    approved: bool = False
    rejected: bool = False
    recipe: dict[str, JsonValue] | None = None
    fidelity: dict[str, JsonValue] | None = None
    vlm_pillar: str | None = None
    vlm_reason: str | None = None
    note_source: str | None = None
    deleted_at: str | None = None

    @model_validator(mode="after")
    def lineage(self) -> Self:
        if (self.origin == "generated") != (self.parent_id is not None and self.recipe is not None):
            raise ValueError("Generated views need a parent photo and a stored recipe")
        return self

    @property
    def pillar_source(self) -> Literal["owner", "d3", "vlm"] | None:
        """FR-04: owner label, else a confident d3 label, else the VLM judge, else none."""
        if self.owner_pillar:
            return "owner"
        if self.model_pillar and (self.model_confidence or 0) >= CONFIDENT:
            return "d3"
        if self.vlm_pillar:
            return "vlm"
        return None

    @property
    def pillar(self) -> str | None:
        source = self.pillar_source
        if source is None:
            return None
        return {"owner": self.owner_pillar, "d3": self.model_pillar, "vlm": self.vlm_pillar}[source]

    @property
    def view_score(self) -> float | None:
        """Rule 6: the weaker of d3's same-place and photoreal answers for a generated view."""
        f = self.fidelity or {}
        same, real = f.get("same_place"), f.get("photoreal")
        if isinstance(same, float) and isinstance(real, float):
            return min(same, real)
        return None

    @property
    def needs_review(self) -> bool:
        return not self.rejected and self.pillar is None

    @property
    def described(self) -> bool:
        """FR-04: owner-written EN/AR lines; optional now that the writer sees the photo."""
        return bool(self.note_en.strip() and self.note_ar.strip()) and self.note_source != "vlm"

    @property
    def usable(self) -> bool:
        """FR-04, rule 6: labelled and (for generated views) owner-approved."""
        if self.rejected or self.deleted_at or not self.rights_confirmed or self.pillar is None:
            return False
        return self.origin == "owner" or self.approved


def inspect_image(data: bytes) -> tuple[str, int, int]:
    """NFR-04: accept only decodable JPEG/PNG/WebP and report display-oriented size."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Images must be at most 25 MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            kind = image.format or ""
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = ImageOps.exif_transpose(image).size
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("Upload a JPEG, PNG or WebP photograph") from None
    if kind not in FORMATS:
        raise ValueError("Upload a JPEG, PNG or WebP photograph")
    return FORMATS[kind], width, height


def strip_metadata(data: bytes) -> bytes:
    """NFR-04: drop EXIF (GPS, device) and bake in its rotation; clean files stay byte-exact."""
    with Image.open(io.BytesIO(data)) as image:
        if not image.getexif():
            return data
        kind = image.format or "JPEG"
        upright = ImageOps.exif_transpose(image)
        buffer = io.BytesIO()
        options: dict[str, int] = {"quality": 95} if kind in ("JPEG", "WEBP") else {}
        upright.save(buffer, format=kind, **options)
        return buffer.getvalue()


class AssetLibrary:
    """FR-04: files live under <workspace>/assets; paths are stored relative to the project root."""

    def __init__(self, workspace: Path, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.workspace = workspace.resolve()
        if not self.workspace.is_relative_to(self.root):
            raise ValueError("Keep the asset workspace under the project root")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.workspace / "assets.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(asset)")}
        for name in ("vlm_pillar", "vlm_reason", "note_source", "deleted_at"):
            if name not in columns:
                self.db.execute(f"ALTER TABLE asset ADD COLUMN {name} TEXT")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield self.db

    def path(self, asset: Asset) -> Path:
        return self.root / asset.file

    def add(
        self,
        data: bytes,
        *,
        added_by: str,
        rights_confirmed: bool,
        note_en: str = "",
        note_ar: str = "",
        origin: Origin = "owner",
        parent_id: str | None = None,
        recipe: dict[str, JsonValue] | None = None,
    ) -> Asset:
        """FR-04: identical bytes are one asset; a re-upload returns the stored row."""
        inspect_image(data)
        data = strip_metadata(data)
        suffix, width, height = inspect_image(data)
        if origin == "owner" and not rights_confirmed:
            raise ValueError("Confirm you own the photo and people in it agreed to be shown")
        sha = hashlib.sha256(data).hexdigest()
        existing = self.find_sha(sha)
        if existing:
            if existing.deleted_at:
                with self.transaction() as db:
                    db.execute("UPDATE asset SET deleted_at = NULL WHERE id = ?", (existing.id,))
                return self.get(existing.id)
            return existing
        folder = self.workspace / "assets" / ("originals" if origin == "owner" else "generated")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{sha[:20]}{suffix}"
        target.write_bytes(data)
        asset = Asset(
            id=f"{'a' if origin == 'owner' else 'g'}-{sha[:12]}",
            sha256=sha,
            file=target.relative_to(self.root).as_posix(),
            width=width,
            height=height,
            origin=origin,
            parent_id=parent_id,
            note_en=note_en.strip(),
            note_ar=note_ar.strip(),
            added_by=added_by,
            rights_confirmed=rights_confirmed,
            created_at=now(),
            recipe=recipe,
        )
        with self.transaction() as db:
            db.execute(
                "INSERT INTO asset (id, sha256, file, width, height, origin, parent_id, note_en,"
                " note_ar, added_by, rights_confirmed, created_at, recipe_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    asset.id,
                    sha,
                    asset.file,
                    width,
                    height,
                    origin,
                    parent_id,
                    asset.note_en,
                    asset.note_ar,
                    added_by,
                    int(rights_confirmed),
                    asset.created_at,
                    json.dumps(recipe, sort_keys=True) if recipe is not None else None,
                ),
            )
        return asset

    def _row(self, row: sqlite3.Row) -> Asset:
        data = dict(row)
        recipe, fidelity = data.pop("recipe_json"), data.pop("fidelity_json")
        return Asset.model_validate(
            data
            | {
                "rights_confirmed": bool(data["rights_confirmed"]),
                "approved": bool(data["approved"]),
                "rejected": bool(data["rejected"]),
                "recipe": json.loads(recipe) if recipe else None,
                "fidelity": json.loads(fidelity) if fidelity else None,
            }
        )

    def find_sha(self, sha: str) -> Asset | None:
        row = self.db.execute("SELECT * FROM asset WHERE sha256 = ?", (sha,)).fetchone()
        return self._row(row) if row else None

    def get(self, asset_id: str) -> Asset:
        row = self.db.execute("SELECT * FROM asset WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return self._row(row)

    def all(self, *, trash: bool = False) -> list[Asset]:
        """FR-04: library photos, or (trash=True) the ones the owner deleted."""
        where = "deleted_at IS NOT NULL" if trash else "deleted_at IS NULL"
        return [
            self._row(r)
            for r in self.db.execute(f"SELECT * FROM asset WHERE {where} ORDER BY created_at, id")
        ]

    # -- owner actions with undo -------------------------------------------------------------

    def _snapshot(self, ids: list[str]) -> dict[str, dict[str, object]]:
        rows = self.db.execute(
            f"SELECT id, {', '.join(UNDOABLE)} FROM asset WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        ).fetchall()
        return {r["id"]: {k: r[k] for k in UNDOABLE} for r in rows}

    def act(self, actor: str, kind: str, summary: str, ids: list[str], **changes: object) -> int:
        """FR-09: change owner fields on many assets in one step that can be undone."""
        unknown = set(changes) - set(UNDOABLE)
        if unknown or not ids:
            raise ValueError("Unknown change or no photos selected")
        before = self._snapshot(ids)
        if len(before) != len(set(ids)):
            raise KeyError("Unknown photo")
        with self.transaction() as db:
            for asset_id in ids:
                assignments = ", ".join(f"{k} = ?" for k in changes)
                values = [int(v) if isinstance(v, bool) else v for v in changes.values()]
                db.execute(f"UPDATE asset SET {assignments} WHERE id = ?", [*values, asset_id])
            cursor = db.execute(
                "INSERT INTO activity (at, actor, kind, summary, undo_json) VALUES (?,?,?,?,?)",
                (now(), actor, kind, summary, json.dumps(before)),
            )
        return int(cursor.lastrowid or 0)

    def log(self, actor: str, kind: str, summary: str) -> None:
        """FR-09: actions that cannot be undone here (e.g. post decisions) still appear."""
        with self.transaction() as db:
            db.execute(
                "INSERT INTO activity (at, actor, kind, summary) VALUES (?,?,?,?)",
                (now(), actor, kind, summary),
            )

    def undo(self, sequence: int | None = None) -> str:
        """FR-09: restore the asset fields an action changed (latest undoable by default)."""
        query = "SELECT * FROM activity WHERE undo_json IS NOT NULL AND undone = 0"
        row = self.db.execute(
            query + (" AND sequence = ?" if sequence else "") + " ORDER BY sequence DESC LIMIT 1",
            (sequence,) if sequence else (),
        ).fetchone()
        if row is None:
            raise ValueError("Nothing to undo")
        before: dict[str, dict[str, object]] = json.loads(row["undo_json"])
        with self.transaction() as db:
            for asset_id, fields in before.items():
                assignments = ", ".join(f"{k} = ?" for k in fields)
                db.execute(
                    f"UPDATE asset SET {assignments} WHERE id = ?", [*fields.values(), asset_id]
                )
            db.execute("UPDATE activity SET undone = 1 WHERE sequence = ?", (row["sequence"],))
        return str(row["summary"])

    def activity(self, limit: int = 100) -> list[dict[str, object]]:
        return [
            {k: r[k] for k in ("sequence", "at", "actor", "kind", "summary", "undone")}
            | {"undoable": r["undo_json"] is not None and not r["undone"]}
            for r in self.db.execute(
                "SELECT * FROM activity ORDER BY sequence DESC LIMIT ?", (limit,)
            )
        ]

    def purge(self, ids: list[str], in_use: set[str]) -> int:
        """FR-04: permanently remove trashed photos no generated post still uses."""
        removed = 0
        for asset in self.all(trash=True):
            if asset.id not in ids or asset.id in in_use:
                continue
            with self.transaction() as db:
                db.execute("DELETE FROM classification WHERE asset_id = ?", (asset.id,))
                db.execute("UPDATE asset SET parent_id = NULL WHERE parent_id = ?", (asset.id,))
                db.execute("DELETE FROM asset WHERE id = ?", (asset.id,))
            self.path(asset).unlink(missing_ok=True)
            removed += 1
        return removed

    def record_classification(
        self,
        asset_id: str,
        *,
        engine_id: str,
        synthetic: bool,
        questions_hash: str,
        answers: dict[str, JsonValue],
        pillar: str | None,
        confidence: float | None,
        people: float | None,
    ) -> None:
        """NFR-03: raw answers are append-only; the asset row keeps the latest summary."""
        with self.transaction() as db:
            db.execute(
                "INSERT INTO classification (asset_id, engine_id, synthetic, questions_hash,"
                " answers_json, created_at) VALUES (?,?,?,?,?,?)",
                (
                    asset_id,
                    engine_id,
                    int(synthetic),
                    questions_hash,
                    json.dumps(answers, sort_keys=True),
                    now(),
                ),
            )
            db.execute(
                "UPDATE asset SET model_pillar = ?, model_confidence = ?, people = ? WHERE id = ?",
                (pillar, confidence, people, asset_id),
            )

    def record_vlm(self, asset_id: str, pillar: str | None, reason: str) -> None:
        """FR-08: second-opinion label for photos d3 was unsure about; never an owner label."""
        with self.transaction() as db:
            db.execute(
                "UPDATE asset SET vlm_pillar = ?, vlm_reason = ? WHERE id = ?",
                (pillar, reason[:500], asset_id),
            )

    def record_fidelity(self, asset_id: str, result: dict[str, JsonValue]) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE asset SET fidelity_json = ? WHERE id = ?",
                (json.dumps(result, sort_keys=True), asset_id),
            )

    def review(
        self,
        asset_id: str,
        *,
        owner_pillar: str | None = None,
        note_en: str | None = None,
        note_ar: str | None = None,
        approved: bool | None = None,
        rejected: bool | None = None,
    ) -> Asset:
        """FR-09: the owner's corrections are stored labels for measuring the classifier."""
        asset = self.get(asset_id)
        update = {
            "owner_pillar": owner_pillar if owner_pillar is not None else asset.owner_pillar,
            "note_en": (note_en if note_en is not None else asset.note_en).strip(),
            "note_ar": (note_ar if note_ar is not None else asset.note_ar).strip(),
            "approved": asset.approved if approved is None else approved,
            "rejected": asset.rejected if rejected is None else rejected,
        }
        with self.transaction() as db:
            db.execute(
                "UPDATE asset SET owner_pillar = ?, note_en = ?, note_ar = ?, approved = ?,"
                " rejected = ?, note_source = ? WHERE id = ?",
                (
                    update["owner_pillar"] or None,
                    update["note_en"],
                    update["note_ar"],
                    int(bool(update["approved"])),
                    int(bool(update["rejected"])),
                    "owner"
                    if (update["note_en"], update["note_ar"]) != (asset.note_en, asset.note_ar)
                    else asset.note_source,
                    asset_id,
                ),
            )
        return self.get(asset_id)

    def setting(self, key: str) -> JsonValue | None:
        row = self.db.execute("SELECT value_json FROM setting WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, key: str, value: JsonValue) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO setting (key, value_json, updated_at) VALUES (?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,"
                " updated_at = excluded.updated_at",
                (key, json.dumps(value, sort_keys=True), now()),
            )
