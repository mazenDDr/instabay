"""FR-06, NFR-03: HUMAN: run on gpu-box after the pinned Wan/runtime spike."""

import importlib
import importlib.metadata
import inspect
import os
from pathlib import Path
from time import perf_counter

from instabay.video.backends.base import BackendCaps, ShotRecipe, ShotResult
from instabay.video.backends.native import checkpoint_directory, require_gpu
from instabay.video.files import RenderError, local_file


class WanDiffusersBackend:
    """NFR-05: optional lazy I2V pipeline; never download weights or install torch."""

    name = "wan"

    def __init__(self, *, confirm_gpu: bool = False, flf_verified: bool = False) -> None:
        self.confirm_gpu, self.flf_verified = confirm_gpu, flf_verified

    def capabilities(self) -> BackendCaps:
        """FR-06: FLF is explicitly verified for the selected checkpoint, not inferred."""
        return BackendCaps(
            flf2v=self.flf_verified, resolutions=["checkpoint-specific"], deterministic=False
        )

    def render_shot(self, shot: ShotRecipe, root: Path, directory: Path) -> ShotResult:
        """NFR-03: CPU generator fresh per call, deterministic flags, one offloaded model."""
        require_gpu(self.confirm_gpu)
        recipe, index = shot.recipe, shot.index
        checkpoint = checkpoint_directory(recipe, root)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":16:8"
        started = perf_counter()
        pipe = None
        try:
            torch = importlib.import_module("torch")
            diffusers = importlib.import_module("diffusers")
            utils = importlib.import_module("diffusers.utils")
            required = {"diffusers", "transformers", "accelerate", "safetensors"}
            if not required <= recipe.runtime.native_packages.keys() or any(
                importlib.metadata.version(name) != version
                for name, version in recipe.runtime.native_packages.items()
            ):
                raise RenderError("Native package versions differ from pinned recipe")
            if not torch.cuda.is_available():
                raise RenderError("CUDA unavailable")
            if (
                torch.__version__ != recipe.runtime.torch
                or torch.version.cuda != recipe.runtime.cuda
                or torch.cuda.get_device_name(0) != recipe.runtime.gpu
                or os.environ.get("INSTABAY_GPU_DRIVER") != recipe.runtime.driver
                or os.environ.get("INSTABAY_WORKER_IMAGE_DIGEST")
                != recipe.runtime.docker_image_digest
            ):
                raise RenderError("GPU runtime differs from pinned recipe")
            torch.use_deterministic_algorithms(True)
            torch.backends.cudnn.benchmark = False
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            pipe = diffusers.WanImageToVideoPipeline.from_pretrained(
                str(checkpoint), local_files_only=True, torch_dtype=torch.bfloat16
            )
            scheduler_class = getattr(diffusers, recipe.model.scheduler)
            settings = {
                k: v for k, v in recipe.model.scheduler_config.items() if k != "local_model_uri"
            }
            pipe.scheduler = scheduler_class.from_config(settings, flow_shift=recipe.model.shift)
            pipe.enable_model_cpu_offload()
            item = recipe.shots.shots[index]
            args = dict(
                image=utils.load_image(str(local_file(root, item.keyframe))),
                prompt=item.motion_prompt,
                negative_prompt=item.negative_prompt,
                height=recipe.motion.height,
                width=recipe.motion.width,
                num_frames=recipe.motion.frames[index],
                num_inference_steps=recipe.model.steps,
                guidance_scale=recipe.model.cfg,
                generator=torch.Generator("cpu").manual_seed(recipe.motion.seeds[index]),
            )
            if item.end_keyframe:
                if (
                    not self.flf_verified
                    or "last_image" not in inspect.signature(pipe.__call__).parameters
                ):
                    raise RenderError("Pinned pipeline does not support verified FLF")
                end = recipe.shots.shots[index + 1].keyframe
                args["last_image"] = utils.load_image(str(local_file(root, end)))
            frames = pipe(**args).frames[0]
            output = directory / f"shot-{index}.mp4"
            utils.export_to_video(frames, str(output), fps=recipe.motion.fps)
            return ShotResult(file=str(output), seconds=perf_counter() - started)
        except RenderError:
            raise
        except Exception:
            raise RenderError("Wan runtime failed; HUMAN: inspect the pinned GPU setup") from None
        finally:
            # No model stays resident between recipes; size/offload suitability is a spike result.
            if pipe is not None:
                del pipe
