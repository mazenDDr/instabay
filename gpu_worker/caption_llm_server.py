"""FR-04, NFR-03: HUMAN run on gpu-box; measured NF4 candidate with pinned local weights."""

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException

from gpu_worker.local_llm_server import NativeRequest

REPO = "Qwen/Qwen3-8B"
REVISION = "b968826d9c46dd6066d109eabc6255188de91218"  # pragma: allowlist secret - public revision
MODEL_ID = REPO + ":nf4@" + REVISION
app = FastAPI(title="Private grounded-caption candidate")
_lock = Lock()
_model: Any = None
_tokenizer: Any = None


def load() -> tuple[Any, Any]:
    """NFR-03: validate every weight file and record runtime/quantization before inference."""
    global _model, _tokenizer
    if _model is None:
        manifest = json.loads(Path("outputs/caption-model-8b.json").read_text())
        if manifest["repo"] != REPO or manifest["revision"] != REVISION:
            raise ValueError("Caption model identity differs")
        for ref in manifest["files"]:
            with Path(ref["uri"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != ref["sha256"]:
                    raise ValueError("Caption model bytes differ")
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        quant = transformers.BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        runtime = {
            "model": MODEL_ID,
            "weights": manifest,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "transformers": importlib.metadata.version("transformers"),
            "bitsandbytes": importlib.metadata.version("bitsandbytes"),
            "quantization": quant.to_dict(),
            "thinking": False,
            "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        Path("outputs/caption-runtime-8b.json").write_text(json.dumps(runtime, indent=2) + "\n")
        path = "data/caption-model-8b"
        _tokenizer = transformers.AutoTokenizer.from_pretrained(path, local_files_only=True)
        _model = transformers.AutoModelForCausalLM.from_pretrained(
            path,
            local_files_only=True,
            dtype=torch.bfloat16,
            quantization_config=quant,
            device_map="cuda",
        )
    return _model, _tokenizer


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL_ID}


@app.post("/warm")
def warm() -> dict[str, str]:
    """NFR-06: explicit model load separate from a bounded caption request."""
    if os.environ.get("INSTABAY_LLM_ENABLED") != "1":
        raise HTTPException(403, "Caption candidate is not enabled")
    with _lock:
        load()
    return {"status": "loaded", "model": MODEL_ID}


@app.post("/generate")
def generate(request: NativeRequest) -> dict[str, Any]:
    """NFR-06: bounded serialized requests; no paid provider or fixture fallback."""
    if os.environ.get("INSTABAY_LLM_ENABLED") != "1" or request.model != MODEL_ID:
        raise HTTPException(403, "Native model is not explicitly enabled or identity differs")
    with _lock:
        try:
            model, tokenizer = load()
            torch = importlib.import_module("torch")
            prompt = (
                request.prompt
                + "\nReturn JSON only, matching this schema:\n"
                + json.dumps(request.output_schema, ensure_ascii=False)
            )
            if request.validation_feedback:
                prompt += "\nCorrect these validation failures: " + request.validation_feedback
            chat = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(request.inputs, ensure_ascii=False)},
            ]
            text = tokenizer.apply_chat_template(
                chat, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
            tokens = tokenizer(text, return_tensors="pt").to("cuda")
            started = perf_counter()
            kwargs: dict[str, Any] = {
                "max_new_tokens": request.max_output_tokens,
                "do_sample": request.temperature > 0,
            }
            if request.temperature > 0:
                kwargs["temperature"] = request.temperature
            with torch.inference_mode():
                result = model.generate(**tokens, **kwargs)
            generated = result[0, tokens.input_ids.shape[1] :]
            output = tokenizer.decode(generated, skip_special_tokens=True).strip()
            if output.startswith("```"):
                output = output.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return {
                "model": MODEL_ID,
                "output_json": output,
                "input_tokens": int(tokens.input_ids.shape[1]),
                "output_tokens": int(generated.shape[0]),
                "cost_usd": 0.0,
                "latency_ms": (perf_counter() - started) * 1000,
            }
        except Exception as error:
            print("Caption candidate failed", type(error).__name__, flush=True)
            raise HTTPException(
                503, "Pinned caption candidate failed; inspect the private runtime"
            ) from None
