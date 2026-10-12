"""FR-06, FR-08: HUMAN run on gpu-box; d3-flash decisions and FLUX.2-klein camera views.

One large model is resident at a time (16 GB card). d3-flash ships bf16-only numerics
(16.8 GB), so its 2 GB token-embedding table stays in CPU RAM and everything else runs on the
GPU; answers are unchanged because no weight is quantized. Start with:

  PYTHONPATH=data/pydeps-d3:. INSTABAY_GPU_ENABLED=1 \
    python -m uvicorn gpu_worker.vision_server:app --host 127.0.0.1 --port 8790
"""

import base64
import hashlib
import importlib
import io
import json
import os
import sys
import time
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

D3_DIR = Path(os.environ.get("INSTABAY_D3_DIR", "data/d3-flash"))
VIEW_DIR = Path(os.environ.get("INSTABAY_VIEW_DIR", "data/flux2-klein-4b"))
D3_MODEL = "vllm-sr/d3-flash"
VIEW_MODEL = "black-forest-labs/FLUX.2-klein-4B"
MAX_IMAGE_BYTES = 25_000_000

app = FastAPI(title="Insta Bay vision service")
_lock = Lock()
_state: dict[str, Any] = {"name": None, "model": None}


def canonical_hash(value: dict[str, Any]) -> str:
    """NFR-03: same hash as instabay.core.schemas.canonical_hash for JSON-mode payloads."""
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def enabled() -> None:
    if os.environ.get("INSTABAY_GPU_ENABLED") != "1":
        raise HTTPException(403, "Vision service is not enabled")


def unload() -> None:
    """NFR-06: free the resident model before loading the other one."""
    if _state["model"] is None:
        return
    torch = importlib.import_module("torch")
    _state["model"], _state["name"] = None, None
    importlib.import_module("gc").collect()
    torch.cuda.empty_cache()


class CPUEmbedding:
    """Token lookup in CPU RAM; vectors are moved to the ids' device (exact bf16 values)."""

    def __new__(cls, embedding: Any) -> Any:
        torch = importlib.import_module("torch")
        nn = torch.nn

        class _CPUEmbedding(nn.Module):  # type: ignore[misc, name-defined]
            def __init__(self, inner: Any) -> None:
                super().__init__()
                self.weight = nn.Parameter(inner.weight.detach().to("cpu"), requires_grad=False)
                self.padding_idx = inner.padding_idx
                self.num_embeddings, self.embedding_dim = self.weight.shape

            def forward(self, ids: Any) -> Any:
                vectors = nn.functional.embedding(ids.to("cpu"), self.weight, self.padding_idx)
                return vectors.to(ids.device, non_blocking=True)

        return _CPUEmbedding(embedding)


def load_d3() -> Any:
    """FR-08: d3's own runtime with the embedding table kept on the CPU."""
    if _state["name"] == "d3":
        return _state["model"]
    unload()
    sys.path.insert(0, str(D3_DIR.resolve()))
    runtime: Any = importlib.import_module("d3_runtime")
    original = runtime.backbone_class

    class Loader:
        @staticmethod
        def from_pretrained(path: str, **kwargs: Any) -> Any:
            kwargs["device_map"] = {
                "language_model.embed_tokens": "cpu",
                "language_model.layers": 0,
                "language_model.norm": 0,
                "language_model.rotary_emb": 0,
                "visual": 0,
            }
            backbone = original(runtime.backbone_type(Path(path))).from_pretrained(path, **kwargs)
            hooks = importlib.import_module("accelerate.hooks")
            hooks.remove_hook_from_module(backbone, recurse=True)
            backbone.language_model.embed_tokens = CPUEmbedding(
                backbone.language_model.embed_tokens
            )
            return backbone

    runtime.backbone_class = lambda kind: Loader
    try:
        model = runtime.D3.from_pretrained(str(D3_DIR), device="cuda:0", batch_size=1)
    finally:
        runtime.backbone_class = original
    _state["model"], _state["name"] = model, "d3"
    return model


def load_view() -> Any:
    """FR-06: FLUX.2-klein-4B in bf16; text encoder offloaded between steps."""
    if _state["name"] == "view":
        return _state["model"]
    unload()
    torch = importlib.import_module("torch")
    diffusers = importlib.import_module("diffusers")
    pipe = diffusers.Flux2KleinPipeline.from_pretrained(str(VIEW_DIR), torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    _state["model"], _state["name"] = pipe, "view"
    return pipe


def decode_image(text: str) -> Any:
    image_module = importlib.import_module("PIL.Image")
    ops = importlib.import_module("PIL.ImageOps")
    data = base64.b64decode(text.split(",")[-1], validate=True)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image too large")
    return ops.exif_transpose(image_module.open(io.BytesIO(data))).convert("RGB")


class SystemOneRequest(BaseModel):
    state: str | dict[str, Any]
    questions: dict[str, dict[str, Any]]
    model: str
    revision: str | None = None
    images: list[str] = Field(default_factory=list, max_length=4)


class ViewRequest(BaseModel):
    image: str
    recipe: dict[str, Any]


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "resident": _state["name"]}


@app.post("/v1/systemone")
def systemone(request: SystemOneRequest) -> dict[str, Any]:
    enabled()
    if request.model != D3_MODEL:
        raise HTTPException(422, "Only d3-flash is served")
    images = [decode_image(i) for i in request.images]
    with _lock:
        model = load_d3()
        started = time.perf_counter()
        result = model.system_one(
            state=request.state, questions=request.questions, images=images or None
        )
    result = dict(result)
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


@app.post("/v1/views")
def views(request: ViewRequest) -> dict[str, Any]:
    enabled()
    recipe = request.recipe
    if recipe.get("model") != VIEW_MODEL or recipe.get("kind") != "camera-view-v1":
        raise HTTPException(422, "Unsupported view recipe")
    source = decode_image(request.image)
    torch = importlib.import_module("torch")
    with _lock:
        pipe = load_view()
        started = time.perf_counter()
        generator = torch.Generator(device="cpu").manual_seed(int(recipe["seed"]))
        image = pipe(
            prompt=recipe["prompt"],
            image=[source],
            width=int(recipe["width"]),
            height=int(recipe["height"]),
            guidance_scale=float(recipe["guidance"]),
            num_inference_steps=int(recipe["steps"]),
            generator=generator,
        ).images[0]
        peak = torch.cuda.max_memory_allocated()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {
        "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "recipe_hash": canonical_hash(recipe),
        "elapsed_s": round(time.perf_counter() - started, 2),
        "peak_bytes": peak,
    }
