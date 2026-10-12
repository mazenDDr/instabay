"""FR-06, rule 6: new camera views of an owner photo that keep the real place; human-approved.

The image model only moves the camera, adds people or changes the hour. A d3-flash check on
(original, view) records whether the place stayed the same; the owner still approves each view.
"""

import base64
import io
import math
import os
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps
from pydantic import Field, JsonValue

from instabay.assets.classify import fidelity_questions
from instabay.assets.library import Asset, AssetLibrary
from instabay.core.schemas import Boundary, canonical_hash
from instabay.decisions.engine import DecisionUnavailableError
from instabay.decisions.vision import VisionDecisionEngine

KEEP = (
    "Keep the exact same resort: every building, roof, pool, jetty, furniture, plant, beach, "
    "rock and coastline must match the reference photo in shape, material and position. "
    "Do not add or remove any building, pool, structure or facility. Photorealistic travel "
    "photograph, natural colours, no illustration, no painting, no text, no watermark."
)

PRESETS: dict[str, tuple[str, str]] = {
    "waterline": (
        "Low angle at the waterline",
        "Move the camera down to just above the water surface, looking across the water toward "
        "the same scene; gentle ripples and clear water fill the foreground.",
    ),
    "aerial": (
        "High aerial view",
        "Move the camera up to a high drone viewpoint looking down at the same scene, showing "
        "the layout of the water, shore and buildings exactly as they are.",
    ),
    "guests": (
        "Guests in the scene",
        "Keep the camera position. Add two relaxed adult guests in swimwear enjoying the "
        "scene naturally, small in the frame, faces turned away from the camera.",
    ),
    "over_shoulder": (
        "Over a guest's shoulder",
        "Place the camera just behind one adult guest's shoulder, out of focus in the near "
        "foreground, looking out at the same scene.",
    ),
    "golden_hour": (
        "Golden hour, wide",
        "Keep the composition wide and the camera slightly lower; render the same scene in "
        "warm late-afternoon golden light with long soft shadows.",
    ),
    "detail": (
        "Close detail",
        "Move the camera close to one real detail visible in the photo (water texture, wood, "
        "sand or plants) with shallow depth of field, the rest of the same scene softly "
        "blurred behind.",
    ),
}

MODEL = "black-forest-labs/FLUX.2-klein-4B"


class ViewRecipe(Boundary):
    """Rule 5: the exact request is stored and hashed with every generated view."""

    kind: str = "camera-view-v1"
    parent_sha256: str
    preset: str
    prompt: str
    model: str = MODEL
    revision: str
    seed: int = Field(ge=0)
    steps: int = Field(default=4, ge=1, le=60)
    guidance: float = Field(default=1.0, ge=0, le=10)
    width: int = Field(ge=1080, le=2048, multiple_of=16)
    height: int = Field(ge=1350, le=2048, multiple_of=16)

    @property
    def hash(self) -> str:
        return canonical_hash(self)


def view_size(width: int, height: int) -> tuple[int, int]:
    """FR-05: smallest parent-shaped size meeting the 1080x1350 feed minimum (multiples of 16)."""
    scale = max(1080 / width, 1350 / height)
    w, h = math.ceil(width * scale / 16) * 16, math.ceil(height * scale / 16) * 16
    if max(w, h) > 2048:
        raise ValueError("Photo is too wide or tall for a feed view; crop it closer to 4:5")
    return w, h


def view_recipe(parent: Asset, preset: str, seed: int, revision: str) -> ViewRecipe:
    if preset not in PRESETS:
        raise ValueError("Unknown camera direction")
    width, height = view_size(parent.width, parent.height)
    return ViewRecipe(
        width=width,
        height=height,
        parent_sha256=parent.sha256,
        preset=preset,
        prompt=f"{PRESETS[preset][1]} {KEEP}",
        revision=revision,
        seed=seed,
    )


class ViewBackend(Protocol):
    """NFR-05: gpu-box service, or the offline stub in tests."""

    backend_id: str

    def render(self, source: bytes, recipe: ViewRecipe) -> bytes: ...


class StubViewBackend:
    """NFR-07: deterministic offline stand-in (mirror + crop); never presented as a model."""

    backend_id = "stub-view-v1"

    def render(self, source: bytes, recipe: ViewRecipe) -> bytes:
        with Image.open(io.BytesIO(source)) as image:
            view = ImageOps.mirror(ImageOps.exif_transpose(image).convert("RGB"))
        width, height = view.size
        inset = (recipe.seed % 7 + 1) * min(width, height) // 40
        view = view.crop((inset, inset, width - inset, height - inset))
        view = view.resize((recipe.width, recipe.height))
        buffer = io.BytesIO()
        view.save(buffer, format="PNG")
        return buffer.getvalue()


class HTTPViewBackend:
    """FR-06: HUMAN-enabled client for gpu_worker/vision_server.py over the SSH tunnel."""

    def __init__(
        self,
        origin: str,
        *,
        confirm_gpu: bool = False,
        timeout_s: float = 600,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parts = urlsplit(origin)
        if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "gpu-box"}:
            raise ValueError("Use the loopback tunnel or gpu-box for the image service")
        self.origin, self.confirm_gpu = origin.rstrip("/"), confirm_gpu
        self.backend_id = "http-view:" + MODEL
        self.client = httpx.Client(
            timeout=timeout_s, follow_redirects=False, trust_env=False, transport=transport
        )

    def render(self, source: bytes, recipe: ViewRecipe) -> bytes:
        if not self.confirm_gpu or os.environ.get("INSTABAY_GPU_ENABLED") != "1":
            raise RuntimeError("HUMAN: set INSTABAY_GPU_ENABLED=1 and --confirm-gpu")
        try:
            response = self.client.post(
                self.origin + "/v1/views",
                json={
                    "image": base64.b64encode(source).decode("ascii"),
                    "recipe": recipe.model_dump(mode="json"),
                },
            )
        except httpx.HTTPError:
            raise RuntimeError("Image service is unreachable; is the tunnel open?") from None
        if response.status_code != 200:
            raise RuntimeError(f"Image service rejected the request (HTTP {response.status_code})")
        body = response.json()
        if body.get("recipe_hash") != recipe.hash:
            raise RuntimeError("Image service rendered a different recipe")
        return base64.b64decode(body["image"])

    def close(self) -> None:
        self.client.close()


def make_view(
    library: AssetLibrary,
    parent: Asset,
    preset: str,
    seed: int,
    *,
    backend: ViewBackend,
    revision: str,
    judge: VisionDecisionEngine | None = None,
) -> Asset:
    """FR-06: identical recipes reuse the stored view; new views wait for owner approval."""
    if parent.origin != "owner":
        raise ValueError("New views start from the owner's real photos only")
    recipe = view_recipe(parent, preset, seed, revision)
    for asset in library.all():
        if asset.recipe and asset.recipe.get("recipe_hash") == recipe.hash:
            return asset
    data = backend.render(library.path(parent).read_bytes(), recipe)
    stored: dict[str, JsonValue] = recipe.model_dump(mode="json") | {
        "recipe_hash": recipe.hash,
        "backend": backend.backend_id,
    }
    view = library.add(
        data,
        added_by=f"{backend.backend_id} for {parent.added_by}",
        rights_confirmed=parent.rights_confirmed,
        note_en=parent.note_en,
        note_ar=parent.note_ar,
        origin="generated",
        parent_id=parent.id,
        recipe=stored,
    )
    if parent.pillar:
        library.record_classification(
            view.id,
            engine_id="inherited:" + parent.id,
            synthetic=False,
            questions_hash=recipe.hash,
            answers={"pillar": parent.pillar},
            pillar=parent.pillar,
            confidence=1.0 if parent.owner_pillar else parent.model_confidence,
            people=None,
        )
    if judge is not None:
        check_fidelity(library, view, judge)
    return library.get(view.id)


def check_fidelity(library: AssetLibrary, view: Asset, judge: VisionDecisionEngine) -> Asset:
    """Rule 6: d3-flash compares (original, view); the score informs, the owner decides."""
    if view.parent_id is None:
        raise ValueError("Only generated views have an original to compare with")
    parent = library.get(view.parent_id)
    try:
        answers = judge.decide(
            "Original resort photograph, then a generated camera view of it.",
            fidelity_questions(),
            [library.path(parent), library.path(view)],
        )
        library.record_fidelity(
            view.id,
            {
                "engine": judge.engine_id,
                "synthetic": judge.synthetic,
                "same_place": answers["same_place"].noul,
                "photoreal": answers["photoreal"].noul,
            },
        )
    except DecisionUnavailableError as error:
        library.record_fidelity(view.id, {"engine": judge.engine_id, "error": str(error)})
    return library.get(view.id)
