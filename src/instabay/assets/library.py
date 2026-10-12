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
  fidelity_json TEXT
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
"""


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

    @model_validator(mode="after")
    def lineage(self) -> Self:
        if (self.origin == "generated") != (self.parent_id is not None and self.recipe is not None):
            raise ValueError("Generated views need a parent photo and a stored recipe")
        return self

    @property
    def pillar(self) -> str | None:
        """FR-04: owner label, else a confident model label, else unassigned."""
        if self.owner_pillar:
            return self.owner_pillar
        if self.model_pillar and (self.model_confidence or 0) >= CONFIDENT:
            return self.model_pillar
        return None

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
        return not self.rejected and (self.pillar is None or not self.described)

    @property
    def described(self) -> bool:
        return bool(self.note_en.strip() and self.note_ar.strip())

    @property
    def usable(self) -> bool:
        """FR-04, rule 6: labelled, described and (for generated views) owner-approved."""
        if self.rejected or not self.rights_confirmed or self.pillar is None or not self.described:
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

    def all(self) -> list[Asset]:
        return [
            self._row(r) for r in self.db.execute("SELECT * FROM asset ORDER BY created_at, id")
        ]

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
                " rejected = ? WHERE id = ?",
                (
                    update["owner_pillar"] or None,
                    update["note_en"],
                    update["note_ar"],
                    int(bool(update["approved"])),
                    int(bool(update["rejected"])),
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
