"""FR-04, NFR-04: explicitly launched private local generation; Python 3.11 GPU-compatible."""

import importlib
import json
import os
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = (
    "cdbee75f17c01a7cc42f958dc650907174af0554"  # pragma: allowlist secret - public model commit
)
MODEL_ID = MODEL + "@" + REVISION


class NativeRequest(BaseModel):
    """FR-04: fully schema-bound inputs; no caller-controlled model path or code."""

    model_config = ConfigDict(extra="forbid")
    model: str
    prompt: str = Field(max_length=20000)
    inputs: dict[str, Any]
    output_schema: dict[str, Any]
    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(gt=0, le=4096)
    validation_feedback: str | None = None


app = FastAPI(title="Insta Bay private local generation")
_lock = Lock()
_model: Any = None
_tokenizer: Any = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL_ID}


@app.post("/generate")
def generate(request: NativeRequest) -> dict[str, Any]:
    """NFR-06: measured token/time metadata; explicit activation, pinned local weights only."""
    global _model, _tokenizer
    if os.environ.get("INSTABAY_LLM_ENABLED") != "1" or request.model != MODEL_ID:
        raise HTTPException(403, "Native model is not explicitly enabled or model identity differs")
    with _lock:
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")

            if _model is None:
                path = (
                    Path.home()
                    / ".cache/huggingface/hub"
                    / ("models--" + MODEL.replace("/", "--"))
                    / "snapshots"
                    / REVISION
                )
                _tokenizer = transformers.AutoTokenizer.from_pretrained(
                    str(path), local_files_only=True
                )
                _model = transformers.AutoModelForCausalLM.from_pretrained(
                    str(path), local_files_only=True, dtype=torch.bfloat16, device_map="cuda"
                )
            instructions = (
                request.prompt
                + "\nReturn only a JSON object matching this schema:\n"
                + json.dumps(request.output_schema, ensure_ascii=False)
            )
            if request.validation_feedback:
                instructions += "\nCorrect these schema errors: " + request.validation_feedback
            chat = [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(request.inputs, ensure_ascii=False)},
            ]
            text = _tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
            tokens = _tokenizer(text, return_tensors="pt").to("cuda")
            started = perf_counter()
            kwargs: dict[str, Any] = {
                "max_new_tokens": request.max_output_tokens,
                "do_sample": request.temperature > 0,
            }
            if request.temperature > 0:
                kwargs["temperature"] = request.temperature
            with torch.inference_mode():
                result = _model.generate(**tokens, **kwargs)
            generated = result[0, tokens.input_ids.shape[1] :]
            output = _tokenizer.decode(generated, skip_special_tokens=True).strip()
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
        except Exception:
            raise HTTPException(
                503, "Pinned local generation failed; inspect the private runtime"
            ) from None
