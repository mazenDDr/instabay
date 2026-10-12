"""FR-06, NFR-03: explicitly authorized, measured I2V experiment on gpu-box (Python 3.11)."""

import argparse
import gc
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field


class PreviewSpec(BaseModel):
    """NFR-03: bounded photo conditioning, pinned weights, and exact small-trial settings."""

    model_config = ConfigDict(extra="forbid")
    repo: str = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    image: str
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str = Field(min_length=1, max_length=2000)
    seeds: list[int] = Field(min_length=1, max_length=3)
    width: int = Field(default=288, ge=128, le=576, multiple_of=32)
    height: int = Field(default=512, ge=128, le=1024, multiple_of=32)
    frames: int = Field(default=61, ge=13, le=81)
    fps: int = Field(default=12, ge=12, le=24)
    steps: int = Field(default=20, ge=8, le=50)
    guidance: float = Field(default=5, ge=1, le=7)
    shift: float = Field(default=5, ge=1, le=12)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--confirm-gpu", action="store_true")
    args = parser.parse_args()
    if not args.confirm_gpu or os.environ.get("INSTABAY_GPU_ENABLED") != "1":
        raise PermissionError("GPU preview requires both explicit opt-ins")
    spec = PreviewSpec.model_validate_json(args.spec.read_bytes())
    if spec.frames % 4 != 1 or any(seed < 0 for seed in spec.seeds):
        raise ValueError("Wan needs 4n+1 frames and nonnegative seeds")
    image = Path(spec.image)
    if sha(image) != spec.image_sha256:
        raise ValueError("Approved crop bytes differ")
    weights = json.loads(Path("outputs/wan-weights.json").read_text())
    if weights["repo"] != spec.repo or weights["revision"] != spec.revision:
        raise ValueError("Downloaded checkpoint identity differs")
    for ref in weights["files"]:
        if sha(Path(ref["uri"])) != ref["sha256"]:
            raise ValueError("Downloaded checkpoint bytes differ")
    torch = importlib.import_module("torch")
    diffusers = importlib.import_module("diffusers")
    utils = importlib.import_module("diffusers.utils")
    pil = importlib.import_module("PIL.Image")
    driver = subprocess.check_output(
        ["/usr/lib/wsl/lib/nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
        text=True,
    ).strip()
    runtime = {
        "python": sys.version,
        "platform": platform.platform(),
        "environment": "prepared conda main; no Docker reproducibility claim",
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "torch",
                "diffusers",
                "transformers",
                "accelerate",
                "safetensors",
                "pillow",
                "imageio-ffmpeg",
            )
        },
        "cuda": torch.version.cuda,
        "driver": driver,
        "gpu": torch.cuda.get_device_name(0),
        "implementation_sha256": sha(Path(__file__)),
    }
    recipe = {
        "kind": "experimental-wan-i2v-motion-v1",
        "spec": spec.model_dump(),
        "weights": weights,
        "runtime": runtime,
        "pipeline_class": "WanImageToVideoPipeline",
        "expand_timesteps": True,
        "scheduler": json.loads(
            Path("data/wan-preview/scheduler/scheduler_config.json").read_text()
        ),
        "offload": "model_cpu_offload; encode prompts once then unload text encoder",
        "vae": "float32, tiling enabled",
        "ai_disclosure": True,
        "reference_only": True,
        "determinism": "Stored artifacts only; no repeated-run or cross-machine claim",
    }
    recipe["scheduler"]["flow_shift"] = spec.shift
    encoded = json.dumps(recipe, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    recipe_hash = hashlib.sha256(encoded).hexdigest()
    directory = Path("outputs/wan-motion") / recipe_hash
    directory.mkdir(parents=True, exist_ok=True)
    recipe_path = directory / "recipe.json"
    if recipe_path.exists():
        raise FileExistsError("Reconcile existing native attempt before retry; never overwrite")
    recipe_path.write_text(json.dumps(recipe, indent=2) + "\n")
    (directory / "worker.py").write_bytes(Path(__file__).read_bytes())
    print("Stored motion recipe", recipe_hash, flush=True)
    started = perf_counter()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    torch.cuda.reset_peak_memory_stats()
    vae = diffusers.AutoencoderKLWan.from_pretrained(
        "data/wan-preview/vae", torch_dtype=torch.float32, local_files_only=True
    )
    pipe = diffusers.WanImageToVideoPipeline.from_pretrained(
        "data/wan-preview",
        vae=vae,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
        expand_timesteps=True,
    )
    pipe.scheduler = diffusers.UniPCMultistepScheduler.from_config(
        pipe.scheduler.config, flow_shift=spec.shift
    )
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_tiling()
    with torch.inference_mode():
        prompt_embeds, negative_embeds = pipe.encode_prompt(
            prompt=spec.prompt,
            negative_prompt=spec.negative_prompt,
            do_classifier_free_guidance=spec.guidance > 1,
            device=torch.device("cuda"),
            num_videos_per_prompt=1,
            max_sequence_length=512,
        )
    if not torch.isfinite(prompt_embeds).all() or (
        negative_embeds is not None and not torch.isfinite(negative_embeds).all()
    ):
        raise ValueError("Non-finite text embeddings: stopped at encoder stage")
    pipe.remove_all_hooks()
    pipe.text_encoder = None
    gc.collect()
    torch.cuda.empty_cache()
    pipe.enable_model_cpu_offload()
    print(
        "Denoiser dtype", pipe.transformer.dtype, "cached embeddings without gradients", flush=True
    )
    source = utils.load_image(str(image))
    clips = []
    for index, seed in enumerate(spec.seeds):
        shot_started = perf_counter()
        frames = pipe(
            image=source,
            prompt_embeds=prompt_embeds,
            negative_prompt_embeds=negative_embeds,
            height=spec.height,
            width=spec.width,
            num_frames=spec.frames,
            num_inference_steps=spec.steps,
            guidance_scale=spec.guidance,
            generator=torch.Generator("cpu").manual_seed(seed),
        ).frames[0]
        output = directory / f"shot-{index}.mp4"
        utils.export_to_video(frames, str(output), fps=spec.fps)
        for label, frame in (
            ("first", frames[0]),
            ("middle", frames[len(frames) // 2]),
            ("last", frames[-1]),
        ):
            pil.fromarray((frame * 255).clip(0, 255).astype("uint8")).save(
                directory / f"shot-{index}-{label}.png"
            )
        clips.append(
            {
                "file": output.as_posix(),
                "sha256": sha(output),
                "seed": seed,
                "seconds": perf_counter() - shot_started,
            }
        )
        (directory / "progress.json").write_text(json.dumps(clips, indent=2) + "\n")
        print("Completed shot", index, "seconds", clips[-1]["seconds"], flush=True)
    result = {
        "recipe_hash": recipe_hash,
        "recipe_file_sha256": sha(recipe_path),
        "clips": clips,
        "seconds": perf_counter() - started,
        "peak_vram_bytes": torch.cuda.max_memory_allocated(),
        "ai_disclosure": True,
        "reference_only": True,
        "cost_usd_api_fees": 0,
        "quality_status": "awaiting visual review; not publish approved",
    }
    (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Native motion completed", recipe_hash, flush=True)


if __name__ == "__main__":
    main()
