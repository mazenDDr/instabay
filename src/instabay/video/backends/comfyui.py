"""FR-06, NFR-05: HUMAN: run a pinned, private ComfyUI worker on gpu-box."""

import json
import re
import time
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from instabay.core.schemas import Boundary, Identifier
from instabay.video.backends.base import BackendCaps, ShotRecipe, ShotResult
from instabay.video.backends.native import require_gpu
from instabay.video.files import RenderError, local_file


class PromptReceipt(Boundary):
    """NFR-03: validate server job identity before bounded history polling."""

    prompt_id: Identifier
    number: int = Field(ge=0)
    node_errors: dict[str, object] = Field(default_factory=dict)


class ComfyUIBackend:
    """NFR-05: trusted API workflow with explicit bindings, no silent missing seed/FLF."""

    name = "comfyui"

    def __init__(
        self,
        origin: str = "http://127.0.0.1:8188",
        *,
        confirm_gpu: bool = False,
        flf_verified: bool = False,
        transport: httpx.BaseTransport | None = None,
        max_polls: int = 120,
        poll_seconds: float = 5,
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "gpu-box", "100.109.90.64"}
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ComfyUI must use a private loopback/Tailscale origin")
        if not 1 <= max_polls <= 720 or not 0 <= poll_seconds <= 10:
            raise ValueError("Polling must be bounded")
        self.client = httpx.Client(
            base_url=origin, timeout=30, transport=transport, trust_env=False
        )
        self.confirm_gpu, self.flf_verified = confirm_gpu, flf_verified
        self.max_polls, self.poll_seconds = max_polls, poll_seconds

    def capabilities(self) -> BackendCaps:
        """FR-06: capabilities follow human-verified pinned workflow."""
        return BackendCaps(flf2v=self.flf_verified, resolutions=["workflow-specific"])

    def close(self) -> None:
        """NFR-06: close private HTTP resources."""
        self.client.close()

    def render_shot(self, shot: ShotRecipe, root: Path, directory: Path) -> ShotResult:
        """NFR-03: upload immutable inputs, bind every render variable and download output."""
        require_gpu(self.confirm_gpu)
        recipe, index = shot.recipe, shot.index
        if recipe.model.workflow is None:
            raise RenderError("No pinned workflow")
        started = perf_counter()
        try:
            workflow = json.loads(local_file(root, recipe.model.workflow).read_bytes())
            bindings = recipe.model.scheduler_config.get("bindings")
            if not isinstance(bindings, dict):
                raise RenderError("Workflow needs explicit variable bindings")
            values: dict[str, object] = {
                "seed": recipe.motion.seeds[index],
                "prompt": recipe.shots.shots[index].motion_prompt,
                "negative_prompt": recipe.shots.shots[index].negative_prompt,
                "width": recipe.motion.width,
                "height": recipe.motion.height,
                "frames": recipe.motion.frames[index],
                "steps": recipe.model.steps,
                "cfg": recipe.model.cfg,
                "shift": recipe.model.shift,
            }
            frames = {"image": recipe.shots.shots[index].keyframe}
            if recipe.shots.shots[index].end_keyframe:
                if not self.flf_verified:
                    raise RenderError("FLF workflow is unverified")
                frames["last_image"] = recipe.shots.shots[index + 1].keyframe
            for key, ref in frames.items():
                path = local_file(root, ref)
                with path.open("rb") as stream:
                    response = self.client.post(
                        "/upload/image",
                        files={"image": (path.name, stream)},
                        data={"overwrite": "false"},
                    )
                response.raise_for_status()
                name = response.json()["name"]
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                    raise RenderError("Unsafe uploaded image identity")
                values[key] = name
            for key, value in values.items():
                binding = bindings.get(key)
                if (
                    not isinstance(binding, list)
                    or len(binding) != 2
                    or not all(isinstance(x, str) for x in binding)
                ):
                    raise RenderError(
                        "Every recipe variable must be bound into the pinned workflow"
                    )
                workflow[binding[0]]["inputs"][binding[1]] = value
            response = self.client.post("/prompt", json={"prompt": workflow})
            response.raise_for_status()
            # Server may add nonessential fields; copy only the validated boundary.
            raw = response.json()
            receipt = PromptReceipt.model_validate(
                {k: raw[k] for k in ("prompt_id", "number", "node_errors") if k in raw}
            )
            if receipt.node_errors:
                raise RenderError("ComfyUI rejected workflow nodes")
            for _ in range(self.max_polls):
                history = self.client.get(f"/history/{receipt.prompt_id}")
                history.raise_for_status()
                entry = history.json().get(receipt.prompt_id)
                if entry:
                    if entry.get("status", {}).get("status_str") == "error":
                        raise RenderError("ComfyUI job failed")
                    files = [
                        v
                        for node in entry.get("outputs", {}).values()
                        for key in ("videos", "gifs")
                        for v in node.get(key, [])
                        if v.get("filename", "").endswith(".mp4")
                    ]
                    if len(files) != 1:
                        raise RenderError("ComfyUI must return exactly one MP4")
                    item = files[0]
                    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.mp4", item["filename"]) or item.get(
                        "subfolder", ""
                    ):
                        raise RenderError("Unsafe ComfyUI output path")
                    download = self.client.get(
                        "/view", params={"filename": item["filename"], "type": "output"}
                    )
                    download.raise_for_status()
                    if len(download.content) > recipe.post.max_bytes:
                        raise RenderError("ComfyUI artifact exceeds configured size")
                    output = directory / f"shot-{index}.mp4"
                    output.write_bytes(download.content)
                    return ShotResult(file=str(output), seconds=perf_counter() - started)
                time.sleep(self.poll_seconds)
            raise RenderError("ComfyUI poll budget exhausted; do not blindly resubmit a GPU job")
        except RenderError:
            raise
        except Exception:
            raise RenderError(
                "ComfyUI failed; HUMAN: inspect the private job before retry"
            ) from None
