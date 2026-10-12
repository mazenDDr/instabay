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
VLM_DIR = Path(os.environ.get("INSTABAY_VLM_DIR", "data/qwen3.5-4b"))
VLM_MODEL = "Qwen/Qwen3.5-4B"
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


def log(event: str, **fields: Any) -> None:
    """NFR-03: one JSON line per load/request so measurements can be read back from the log."""
    print(json.dumps({"event": event, **fields}), flush=True)


def gpu_bytes() -> dict[str, int]:
    torch = importlib.import_module("torch")
    return {
        "allocated": torch.cuda.memory_allocated(),
        "peak": torch.cuda.max_memory_allocated(),
    }


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
    started = time.perf_counter()
    try:
        model = runtime.D3.from_pretrained(str(D3_DIR), device="cuda:0", batch_size=1)
    finally:
        runtime.backbone_class = original
    _state["model"], _state["name"] = model, "d3"
    log("load", model=D3_MODEL, seconds=round(time.perf_counter() - started, 1), **gpu_bytes())
    return model


def load_view() -> Any:
    """FR-06: FLUX.2-klein-4B in bf16; text encoder offloaded between steps."""
    if _state["name"] == "view":
        return _state["model"]
    unload()
    started = time.perf_counter()
    torch = importlib.import_module("torch")
    diffusers = importlib.import_module("diffusers")
    pipe = diffusers.Flux2KleinPipeline.from_pretrained(str(VIEW_DIR), torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    _state["model"], _state["name"] = pipe, "view"
    log("load", model=VIEW_MODEL, seconds=round(time.perf_counter() - started, 1), **gpu_bytes())
    return pipe


def load_vlm() -> Any:
    """FR-08: Qwen3.5-4B in bf16 (about 9 GB) as a second-opinion pillar judge."""
    if _state["name"] == "vlm":
        return _state["model"]
    unload()
    started = time.perf_counter()
    torch = importlib.import_module("torch")
    transformers = importlib.import_module("transformers")
    processor = transformers.AutoProcessor.from_pretrained(str(VLM_DIR))
    model = transformers.AutoModelForImageTextToText.from_pretrained(
        str(VLM_DIR), dtype=torch.bfloat16, device_map="cuda:0"
    ).eval()
    _state["model"], _state["name"] = (model, processor), "vlm"
    log("load", model=VLM_MODEL, seconds=round(time.perf_counter() - started, 1), **gpu_bytes())
    return _state["model"]


def parse_verdict(text: str, options: dict[str, str]) -> dict[str, Any]:
    """FR-08: accept only a JSON object naming one requested option; otherwise abstain."""
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start : end + 1]) if start >= 0 else {}
    except ValueError:
        data = {}
    choice = data.get("pillar") if isinstance(data, dict) else None
    reason = str(data.get("reason", "")) if isinstance(data, dict) else ""
    if choice not in options:
        return {"choice": None, "reason": "Unparseable answer: " + text[:200]}
    return {"choice": choice, "reason": reason[:500]}


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


class VLMRequest(BaseModel):
    model: str
    image: str
    instructions: str = Field(max_length=2000)
    options: dict[str, str] = Field(min_length=2, max_length=12)


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
    log(
        "systemone",
        images=len(images),
        questions=len(request.questions),
        ms=result["elapsed_ms"],
        answers=result.get("answers"),
        **gpu_bytes(),
    )
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
        torch.cuda.reset_peak_memory_stats()
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
    seconds = round(time.perf_counter() - started, 2)
    log("view", preset=recipe.get("preset"), seconds=seconds, size=list(image.size), peak=peak)
    return {
        "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "recipe_hash": canonical_hash(recipe),
        "elapsed_s": seconds,
        "peak_bytes": peak,
    }


@app.post("/v1/vlm-choice")
def vlm_choice(request: VLMRequest) -> dict[str, Any]:
    enabled()
    if request.model != VLM_MODEL:
        raise HTTPException(422, "Only Qwen3.5-4B is served as the judge")
    image = decode_image(request.image)
    image.thumbnail((1280, 1280))
    listing = "\n".join(f"- {key}: {text}" for key, text in request.options.items())
    prompt = (
        f"{request.instructions}\n\nPillars:\n{listing}\n\n"
        'Answer with JSON only: {"pillar": "<one id from the list>", '
        '"reason": "<one short sentence about what is visible>"}'
    )
    torch = importlib.import_module("torch")
    with _lock:
        model, processor = load_vlm()
        started = time.perf_counter()
        messages = [
            {
                "role": "user",
                "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}],
            }
        ]
        inputs = processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        ).to(model.device)
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=160, do_sample=False)
        text = processor.decode(
            output[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
        ).strip()
    verdict = parse_verdict(text, request.options)
    ms = round((time.perf_counter() - started) * 1000, 1)
    log("vlm", ms=ms, verdict=verdict, raw=text[:300], **gpu_bytes())
    return {"verdict": verdict, "raw": text, "elapsed_ms": ms}
