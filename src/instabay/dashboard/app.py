"""FR-02, FR-04, FR-09, FR-11: local owner dashboard (Meta Business Suite style).

Binds to loopback only. The owner's Approve/Reject clicks are stored exactly like CLI
approvals; publishing stays an explicit CLI action (`instabay resume` / `cycle`).
"""

import base64
import binascii
import io
import os
import shutil
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from PIL import Image, ImageOps
from pydantic import Field, JsonValue

from instabay.assets.classify import agreement, classify_assets
from instabay.assets.export import PROPERTY_KEY
from instabay.assets.judge import PillarJudge
from instabay.assets.library import VIEW_OK, Asset, AssetLibrary
from instabay.assets.plan import OwnerCadence, load_cadence, save_cadence, suggest_assets
from instabay.content.feedback import collect, for_writers
from instabay.core.planner import plan_week
from instabay.core.schemas import ApprovalRequest, Boundary, BrandConstitution, canonical_hash
from instabay.dashboard import data
from instabay.dashboard.jobs import FORGOTTEN_KEY, Pipeline, next_monday
from instabay.decisions.vision import VisionDecisionEngine

PAGE = Path(__file__).with_name("index.html")
THUMB = 520
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"}
PILLAR_NAMES = {
    "underwater": "Water & nature",
    "spa": "Relaxation",
    "guests": "Stay inspiration",
    "local": "The setting",
    "offers": "Travel planning",
}


class Upload(Boundary):
    """FR-04: browser upload as base64 so no multipart dependency is needed."""

    name: str = Field(max_length=200)
    data_base64: str = Field(max_length=34_000_000)
    note_en: str = Field(default="", max_length=600)
    note_ar: str = Field(default="", max_length=600)
    rights_confirmed: bool
    added_by: str = Field(min_length=1, max_length=80)


class AssetUpdate(Boundary):
    owner_pillar: str | None = None
    note_en: str | None = Field(default=None, max_length=600)
    note_ar: str | None = Field(default=None, max_length=600)
    approved: bool | None = None
    rejected: bool | None = None


class Decision(Boundary):
    db: str = Field(min_length=1, max_length=400)
    post_id: str = Field(min_length=1, max_length=200)
    decision: str = Field(pattern="^(APPROVED|REJECTED|EDITED|REVOKED)$")
    actor: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=600)
    seconds_spent: float = Field(default=0, ge=0, le=86400)
    en_caption: str | None = Field(default=None, max_length=2200)
    ar_caption: str | None = Field(default=None, max_length=2200)


class BulkDecision(Boundary):
    db: str = Field(min_length=1, max_length=400)
    post_ids: list[str] = Field(min_length=1, max_length=50)
    decision: str = Field(pattern="^(APPROVED|REJECTED|REVOKED)$")
    actor: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=600)


class AssetAction(Boundary):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: str = Field(pattern="^(delete|restore|hide|show|pillar|approve|unapprove)$")
    pillar: str | None = None
    actor: str = Field(default="owner", min_length=1, max_length=80)


class Forget(Boundary):
    id: str | None = Field(default=None, max_length=40)
    restore_all: bool = False


class Undo(Boundary):
    sequence: int | None = None


class Purge(Boundary):
    ids: list[str] | None = None


class RunRef(Boundary):
    db: str = Field(min_length=1, max_length=400)


class GenerateRequest(Boundary):
    actor: str = Field(min_length=1, max_length=80)
    week_start: str | None = None
    freeze_confirmed: bool
    mode: str = Field(default="autopilot", pattern="^(autopilot|guided)$")
    again: bool = False


class PropertyUpdate(Boundary):
    name: str = Field(min_length=1, max_length=120)


class VariantRequest(Boundary):
    preset: str = Field(min_length=1, max_length=60)
    seed: int = Field(default=0, ge=0)


def asset_view(asset: Asset) -> dict[str, JsonValue]:
    data = asset.model_dump(mode="json", exclude={"recipe", "fidelity"})
    return data | {
        "pillar": asset.pillar,
        "needs_review": asset.needs_review,
        "usable": asset.usable,
        "described": asset.described,
        "preset": (asset.recipe or {}).get("preset"),
        "pillar_source": asset.pillar_source,
        "low_res": min(asset.width, asset.height) < 1080,
        "view_score": asset.view_score,
        "view_ok": asset.view_score is not None and asset.view_score >= VIEW_OK,
        "fidelity": asset.fidelity,
        "thumb": f"/media/assets/{asset.id}?w={THUMB}",
        "full": f"/media/assets/{asset.id}",
    }


def create_app(
    *,
    workspace: Path,
    brand: BrandConstitution,
    runs: Path,
    root: Path | None = None,
    engine: VisionDecisionEngine | None = None,
    judge: PillarJudge | None = None,
    variants: Callable[[AssetLibrary, Asset, str, int], Asset] | None = None,
    shots: Callable[[AssetLibrary, Asset], Asset] | None = None,
    presets: dict[str, str] | None = None,
    pipeline: Pipeline | None = None,
) -> FastAPI:
    """FR-04: one library connection per request keeps SQLite writes serialized."""
    root = (root or Path.cwd()).resolve()
    runs = runs.resolve()
    if not runs.is_relative_to(root):
        raise ValueError("Runs folder must be under the project root")
    app = FastAPI(title="Insta Bay owner dashboard", docs_url=None, redoc_url=None)

    def library() -> AssetLibrary:
        return AssetLibrary(workspace, root=root)

    def known(pillar: str | None) -> None:
        if pillar and pillar not in {p.id for p in brand.pillars}:
            raise HTTPException(422, "Unknown pillar")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE.read_text()

    @app.get("/api/summary")
    def summary() -> dict[str, JsonValue]:
        with library() as lib:
            assets = lib.all()
            cadence = load_cadence(lib, brand)
            property_name = lib.setting(PROPERTY_KEY) or "Insta Bay"
        usable = [a for a in assets if a.usable]
        return {
            "property": property_name,
            "pillars": [
                {
                    "id": p.id,
                    "name": PILLAR_NAMES.get(p.id, p.id),
                    "description": p.description,
                    "min_share": p.min_share,
                    "max_share": p.max_share,
                    "photos": sum(a.pillar == p.id for a in usable),
                }
                for p in brand.pillars
            ],
            "cadence": cadence.model_dump(mode="json")
            | {"photos_per_week": cadence.photos_per_week},
            "assets": {
                "total": len(assets),
                "owner": sum(a.origin == "owner" for a in assets),
                "generated": sum(a.origin == "generated" for a in assets),
                "usable": len(usable),
                "needs_review": sum(a.needs_review for a in assets),
            },
            "agreement": agreement(assets).model_dump(mode="json"),
            "vlm_agreement": agreement(assets, "vlm").model_dump(mode="json"),
            "engine": engine.engine_id if engine else None,
            "engine_synthetic": engine.synthetic if engine else None,
            "variants_enabled": variants is not None,
            "judge": judge.judge_id if judge else None,
            "generate": pipeline is not None,
            "instagram": {
                "configured": bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN"))
                and bool(os.environ.get("INSTAGRAM_USER_ID")),
                "mode": os.environ.get("INSTABAY_MODE", "dry_run"),
            },
            "low_res": sum(min(a.width, a.height) < 1080 for a in assets if a.origin == "owner"),
            "presets": [{"id": k, "label": v} for k, v in (presets or {}).items()],
        }

    @app.get("/api/assets")
    def list_assets() -> list[dict[str, JsonValue]]:
        with library() as lib:
            return [asset_view(a) for a in reversed(lib.all())]

    @app.post("/api/assets")
    def upload(item: Upload) -> dict[str, JsonValue]:
        try:
            data = base64.b64decode(item.data_base64.split(",")[-1], validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Upload is not valid base64") from None
        with library() as lib:
            try:
                asset = lib.add(
                    data,
                    added_by=item.added_by,
                    rights_confirmed=item.rights_confirmed,
                    note_en=item.note_en,
                    note_ar=item.note_ar,
                )
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            lib.log(item.added_by, "upload", f"added {item.name} ({asset.id})")
            return asset_view(asset)

    @app.patch("/api/assets/{asset_id}")
    def update(asset_id: str, change: AssetUpdate) -> dict[str, JsonValue]:
        known(change.owner_pillar)
        with library() as lib:
            try:
                lib.get(asset_id)
            except KeyError:
                raise HTTPException(404, "Unknown asset") from None
            return asset_view(lib.review(asset_id, **change.model_dump(exclude_none=True)))

    @app.post("/api/classify")
    def classify(force: bool = False) -> dict[str, JsonValue]:
        if engine is None:
            raise HTTPException(409, "Start the dashboard with a vision engine to classify")
        with library() as lib:
            report = classify_assets(lib, engine, brand, force=force, judge=judge)
            return report.model_dump(mode="json") | {
                "agreement": agreement(lib.all()).model_dump(mode="json")
            }

    @app.post("/api/assets/{asset_id}/variants")
    def variant(asset_id: str, request: VariantRequest) -> dict[str, JsonValue]:
        if variants is None:
            raise HTTPException(409, "Start the dashboard with the gpu-box image service")
        with library() as lib:
            try:
                parent = lib.get(asset_id)
            except KeyError:
                raise HTTPException(404, "Unknown asset") from None
            if parent.origin != "owner":
                raise HTTPException(422, "Generate new views only from the owner's real photos")
            try:
                return asset_view(variants(lib, parent, request.preset, request.seed))
            except (ValueError, RuntimeError) as error:
                raise HTTPException(502, str(error)) from None

    @app.put("/api/property")
    def put_property(value: PropertyUpdate) -> dict[str, str]:
        with library() as lib:
            lib.set_setting(PROPERTY_KEY, value.name.strip())
        return {"property": value.name.strip()}

    @app.get("/api/cadence")
    def get_cadence() -> dict[str, JsonValue]:
        with library() as lib:
            value = load_cadence(lib, brand)
        return value.model_dump(mode="json") | {"photos_per_week": value.photos_per_week}

    @app.put("/api/cadence")
    def put_cadence(value: OwnerCadence) -> dict[str, JsonValue]:
        with library() as lib:
            try:
                save_cadence(lib, brand, value)
            except ValueError as error:
                raise HTTPException(422, str(error).splitlines()[0]) from None
        return value.model_dump(mode="json") | {"photos_per_week": value.photos_per_week}

    @app.get("/api/plan")
    def plan(week_start: str | None = None) -> dict[str, JsonValue]:
        start = date.fromisoformat(week_start) if week_start else date.today()
        start -= timedelta(days=start.weekday())
        with library() as lib:
            assets = lib.all()
            rhythm = load_cadence(lib, brand).cadence(brand)
        slots = plan_week(brand, canonical_hash(brand), "preview", start, cadence=rhythm)
        suggestions = suggest_assets(slots, assets)
        views = {a.id: asset_view(a) for a in assets}
        return {
            "week_start": start.isoformat(),
            "slots": [
                {
                    "id": s.id,
                    "day": s.scheduled_at.strftime("%A"),
                    "time": s.scheduled_at.strftime("%H:%M"),
                    "pillar": s.arm.pillar,
                    "pillar_name": PILLAR_NAMES.get(s.arm.pillar, s.arm.pillar),
                    "format": s.arm.format,
                    "explore": s.explore,
                    "shortfall": suggestions[s.id].shortfall,
                    "matching": suggestions[s.id].matching,
                    "primary": [views[i] for i in suggestions[s.id].primary],
                    "alternatives": [
                        views[i]
                        for i in suggestions[s.id].pool
                        if i not in suggestions[s.id].primary
                    ],
                }
                for s in slots
            ],
        }

    @app.get("/api/generate")
    def generation() -> dict[str, JsonValue]:
        status = pipeline.current() if pipeline else None
        return {
            "enabled": pipeline is not None,
            "next_week": next_monday().isoformat(),
            "job": status.model_dump(mode="json") if status else None,
        }

    @app.post("/api/generate")
    def generate(item: GenerateRequest) -> dict[str, JsonValue]:
        """FR-01, FR-09: the owner's tick freezes the brand; the run stops at approval."""
        if pipeline is None:
            raise HTTPException(409, "Start the studio with --generate (make studio)")
        if not item.freeze_confirmed:
            raise HTTPException(422, "Confirm the brand before generating")
        try:
            week = date.fromisoformat(item.week_start) if item.week_start else next_monday()
            status = pipeline.start(
                item.actor.strip(),
                week,
                item.mode,  # type: ignore[arg-type]
                again=item.again,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return status.model_dump(mode="json")

    @app.post("/api/generate/continue")
    def resume() -> dict[str, JsonValue]:
        """FR-09: step-by-step mode moves on only when the owner says so."""
        if pipeline is None:
            raise HTTPException(409, "Generation is not enabled")
        try:
            return pipeline.resume().model_dump(mode="json")
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, JsonValue]]:
        return data.summaries(data.discover(runs), root)

    @app.post("/api/decision")
    def decision(item: Decision) -> dict[str, str]:
        """FR-09: one human decision on the exact stored post; flagged posts need a reason."""
        db_path = (root / item.db).resolve()
        if not db_path.is_relative_to(runs) or db_path not in data.discover(runs):
            raise HTTPException(404, "Unknown run database")
        try:
            request = ApprovalRequest(
                decision=item.decision,  # type: ignore[arg-type]
                actor=item.actor,
                reason=item.reason,
                seconds_spent=item.seconds_spent,
                en_caption=item.en_caption,
                ar_caption=item.ar_caption,
            )
            stored = data.decide(db_path, item.post_id, request)
        except KeyError:
            raise HTTPException(404, "Unknown post") from None
        except ValueError as error:
            raise HTTPException(422, str(error).splitlines()[0]) from None
        with library() as lib:
            lib.log(item.actor, "decision", f"{stored.lower()} {item.post_id}")
        return {"decision": stored}

    @app.post("/api/decision/bulk")
    def bulk_decision(item: BulkDecision) -> dict[str, JsonValue]:
        """FR-09: one reason for several posts; each is still stored against its own hash."""
        db_path = (root / item.db).resolve()
        if not db_path.is_relative_to(runs) or db_path not in data.discover(runs):
            raise HTTPException(404, "Unknown run database")
        done: list[str] = []
        failed: dict[str, str] = {}
        for post_id in item.post_ids:
            try:
                request = ApprovalRequest(
                    decision=item.decision,  # type: ignore[arg-type]
                    actor=item.actor,
                    reason=item.reason,
                    seconds_spent=0,
                )
                data.decide(db_path, post_id, request)
                done.append(post_id)
            except (KeyError, ValueError) as error:
                failed[post_id] = str(error).splitlines()[0]
        with library() as lib:
            lib.log(item.actor, "decision", f"{item.decision.lower()} {len(done)} posts")
        return {"done": done, "failed": failed}  # type: ignore[dict-item]

    @app.post("/api/generate/cancel")
    def cancel() -> dict[str, JsonValue]:
        if pipeline is None:
            raise HTTPException(409, "Generation is not enabled")
        try:
            return pipeline.cancel().model_dump(mode="json")
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/runs/delete")
    def delete_run(item: RunRef) -> dict[str, str]:
        """FR-09: a week's folder moves to data/backup-runs; nothing is erased."""
        db_path = (root / item.db).resolve()
        folder = db_path.parent
        if db_path not in data.discover(runs) or folder == runs or not folder.is_relative_to(runs):
            raise HTTPException(404, "Unknown run")
        if (
            pipeline is not None
            and (status := pipeline.current())
            and status.state
            in (
                "running",
                "paused",
            )
            and (root / status.output).resolve() == folder
        ):
            raise HTTPException(409, "Stop the run first")
        target = root / "data" / "backup-runs" / f"{folder.name}-{int(time.time())}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder), target)
        with library() as lib:
            lib.log("owner", "run", f"moved {folder.name} to {target.relative_to(root)}")
        return {"moved_to": target.relative_to(root).as_posix()}

    @app.post("/api/assets/action")
    def asset_action(item: AssetAction) -> dict[str, JsonValue]:
        """FR-04, FR-09: bulk library changes, each one undoable."""
        options: dict[str, dict[str, object]] = {
            "delete": {"deleted_at": datetime.now(UTC).isoformat()},
            "restore": {"deleted_at": None},
            "hide": {"rejected": True},
            "show": {"rejected": False},
            "pillar": {"owner_pillar": item.pillar},
            "approve": {"approved": True, "rejected": False},
            "unapprove": {"approved": False},
        }
        changes = options[item.action]
        if item.action == "pillar":
            known(item.pillar)
            if not item.pillar:
                raise HTTPException(422, "Choose a pillar")
        words = {
            "delete": "moved to Trash",
            "restore": "restored",
            "hide": "hidden",
            "show": "shown",
            "pillar": f"set to {PILLAR_NAMES.get(item.pillar or '', item.pillar)}",
            "approve": "approved",
            "unapprove": "unapproved",
        }
        summary = f"{len(item.ids)} photo{'s' if len(item.ids) != 1 else ''} {words[item.action]}"
        with library() as lib:
            try:
                sequence = lib.act(item.actor, item.action, summary, item.ids, **changes)
            except KeyError:
                raise HTTPException(404, "Unknown photo") from None
        return {"sequence": sequence, "summary": summary}

    @app.post("/api/undo")
    def undo(item: Undo) -> dict[str, str]:
        with library() as lib:
            try:
                return {"undone": lib.undo(item.sequence)}
            except ValueError as error:
                raise HTTPException(409, str(error)) from None

    def forgotten(lib: AssetLibrary) -> set[str]:
        stored = lib.setting(FORGOTTEN_KEY)
        return {str(i) for i in stored} if isinstance(stored, list) else set()

    @app.get("/api/feedback")
    def feedback() -> dict[str, JsonValue]:
        """FR-04: the notes the writers will receive for the next week."""
        with library() as lib:
            skip = forgotten(lib)
        lessons = collect(data.discover(runs), skip)
        return {
            "lessons": [x.model_dump(mode="json") for x in lessons],
            "writers": for_writers(lessons).model_dump(mode="json"),
            "forgotten": len(skip),
        }

    @app.post("/api/feedback/forget")
    def forget(item: Forget) -> dict[str, int]:
        with library() as lib:
            skip = forgotten(lib) | ({item.id} if item.id else set())
            if item.restore_all:
                skip = set()
            ids: list[JsonValue] = [*sorted(skip)]
            lib.set_setting(FORGOTTEN_KEY, ids)
            lib.log(
                "owner",
                "feedback",
                "restored all notes" if item.restore_all else f"forgot note {item.id}",
            )
        return {"forgotten": len(skip)}

    @app.get("/api/activity")
    def activity() -> list[dict[str, JsonValue]]:
        with library() as lib:
            return lib.activity()  # type: ignore[return-value]

    @app.get("/api/trash")
    def trash() -> list[dict[str, JsonValue]]:
        with library() as lib:
            return [asset_view(a) for a in reversed(lib.all(trash=True))]

    @app.post("/api/trash/empty")
    def empty_trash(item: Purge) -> dict[str, JsonValue]:
        """FR-04: permanent; photos still used by a generated post are kept."""
        in_use = data.used_media(data.discover(runs))
        with library() as lib:
            ids = item.ids or [a.id for a in lib.all(trash=True)]
            removed = lib.purge(ids, in_use)
            kept = [i for i in ids if i in in_use]
            lib.log("owner", "trash", f"emptied {removed} photos; kept {len(kept)} in use")
        return {"removed": removed, "kept_in_use": kept}  # type: ignore[dict-item]

    @app.post("/api/assets/{asset_id}/reclassify")
    def reclassify(asset_id: str) -> dict[str, JsonValue]:
        if engine is None:
            raise HTTPException(409, "Start the dashboard with a vision engine to classify")
        with library() as lib:
            try:
                lib.get(asset_id)
            except KeyError:
                raise HTTPException(404, "Unknown photo") from None
            classify_assets(lib, engine, brand, force=True, judge=judge, only={asset_id})
            return asset_view(lib.get(asset_id))

    @app.post("/api/assets/{asset_id}/another")
    def another(asset_id: str) -> dict[str, JsonValue]:
        """FR-06: a new attempt at an AI shot from the same photos; the old one stays."""
        if shots is None:
            raise HTTPException(409, "Start the studio with the gpu-box image service")
        with library() as lib:
            try:
                old = lib.get(asset_id)
            except KeyError:
                raise HTTPException(404, "Unknown photo") from None
            if old.origin != "generated" or not old.recipe:
                raise HTTPException(422, "Only AI shots can be tried again")
            try:
                fresh = shots(lib, old)
            except (ValueError, RuntimeError) as error:
                raise HTTPException(502, str(error)) from None
            lib.log("owner", "shot", f"new attempt {fresh.id} for {old.id}")
            return asset_view(fresh)

    @app.get("/media/assets/{asset_id}")
    def asset_media(asset_id: str, w: int | None = None, download: bool = False) -> Response:
        with library() as lib:
            try:
                path = lib.path(lib.get(asset_id))
            except KeyError:
                raise HTTPException(404, "Unknown asset") from None
        if download:
            return FileResponse(path, filename=f"{asset_id}{path.suffix}")
        if not w:
            return FileResponse(path)
        cache = workspace / "thumbs" / f"{path.stem}-{w}.jpg"
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(path) as image:
                small = ImageOps.exif_transpose(image).convert("RGB")
                small.thumbnail((w, w))
                buffer = io.BytesIO()
                small.save(buffer, format="JPEG", quality=85)
                cache.write_bytes(buffer.getvalue())
        return FileResponse(cache, media_type="image/jpeg")

    @app.get("/media/run")
    def run_media(path: str) -> FileResponse:
        """NFR-04: only image/video files inside the project, never dotfiles such as .env."""
        target = (root / path).resolve()
        if (
            not target.is_relative_to(root)
            or target.suffix.lower() not in MEDIA_SUFFIXES
            or any(part.startswith(".") for part in target.relative_to(root).parts)
            or not target.is_file()
        ):
            raise HTTPException(404, "Unknown media")
        return FileResponse(target)

    return app
