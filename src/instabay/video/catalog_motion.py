"""FR-06, NFR-03: animate approved photos on gpu-box, then bind immutable clips to sources."""

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Protocol

from gpu_worker.wan_preview import PreviewSpec
from instabay.core.motion_capture import (
    MotionCapture,
    MotionReceipt,
    MotionStatus,
    NativeMotionRecipe,
)
from instabay.core.schemas import canonical_hash
from instabay.video.direction import ConditioningCrop, ObjectCatalog, resolve_object
from instabay.video.files import digest, local_file, probe
from instabay.video.shotlist import FileRef, SourceClip

REVISION = "b8fff7315c768468a5333511427288870b2e9635"  # pragma: allowlist secret - public revision


class MotionTransport(Protocol):
    """NFR-05: transport can be replaced by an offline test double."""

    def run(self, args: list[str]) -> str: ...
    def upload(self, source: Path, remote: str) -> None: ...
    def download(self, remote: str, target: Path) -> None: ...


class SSHMotionTransport:
    """NFR-04: fixed private host, quoted remote arguments; no public GPU endpoint."""

    def __init__(self, remote_root: str = "/home/mazen/instabay-native") -> None:
        self.remote_root = remote_root

    def run(self, args: list[str]) -> str:
        command = f"cd {shlex.quote(self.remote_root)} && {shlex.join(args)}"
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "ServerAliveInterval=30",
                "gpu-box",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Private motion command failed; inspect the remote job log")
        return result.stdout.strip()

    def upload(self, source: Path, remote: str) -> None:
        self._copy([str(source), f"gpu-box:{self.remote_root}/{remote}"])

    def download(self, remote: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        self._copy([f"gpu-box:{self.remote_root}/{remote}", str(target)])

    @staticmethod
    def _copy(args: list[str]) -> None:
        result = subprocess.run(
            ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", *args],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Private motion file transfer failed")


def animate_catalog(
    catalog: ObjectCatalog,
    root: Path,
    output: Path,
    *,
    confirm_gpu: bool,
    max_minutes: float = 45,
    seed: int = 2500,
    transport: MotionTransport | None = None,
) -> ObjectCatalog:
    """FR-06: small physical motion from each photo; no manual film endpoints or publishing."""
    if not confirm_gpu or os.environ.get("INSTABAY_GPU_ENABLED") != "1":
        raise PermissionError("Photo animation requires INSTABAY_GPU_ENABLED=1 and --confirm-gpu")
    root, output = root.resolve(), output.resolve()
    if not output.is_relative_to(root) or catalog.edit_style != "scenic":
        raise ValueError("Use a scenic catalog and output under the project root")
    if seed < 0 or max_minutes <= 0:
        raise ValueError("Motion seed and budget are invalid")
    output.mkdir(parents=True, exist_ok=True)
    omit = {"objects": {"__all__": {"clip", "conditioning"}}}
    prompt_dir = Path(__file__).parents[1] / "prompts"
    binding = {
        "catalog_hash": canonical_hash(catalog.model_dump(exclude=omit)),
        "seed": seed,
        "revision": REVISION,
        "prompt_hash": digest(prompt_dir / "motion_source.md"),
        "negative_prompt_hash": digest(prompt_dir / "motion_negative.md"),
    }
    manifest = output / "animation-manifest.json"
    if manifest.exists() and json.loads(manifest.read_text()) != binding:
        raise ValueError("Animation inputs changed; choose a new output directory")
    manifest.write_text(json.dumps(binding, indent=2) + "\n")
    partial = output / "catalog.partial.json"
    if partial.exists():
        saved = ObjectCatalog.model_validate_json(partial.read_bytes())
        omit = {"objects": {"__all__": {"clip", "conditioning"}}}
        if saved.model_dump(exclude=omit) != catalog.model_dump(exclude=omit):
            raise ValueError("Animation sources changed; choose a new output directory")
        if any(
            a.clip and a.clip != b.clip for a, b in zip(catalog.objects, saved.objects, strict=True)
        ):
            raise ValueError("Animation footage changed; choose a new output directory")
        catalog = saved
    missing = sum(o.clip is None for o in catalog.objects)
    if missing * 7 > max_minutes:
        raise ValueError("Estimated motion work exceeds the GPU-minute budget")
    output.mkdir(parents=True, exist_ok=True)
    tx = transport or SSHMotionTransport()
    python = "/home/mazen/miniconda3/envs/main/bin/python"
    started = time.monotonic()
    objects = []
    for index, obj in enumerate(catalog.objects):
        if obj.source != "photo":
            raise ValueError("Only approved real photographs can condition resort footage")
        key = resolve_object(obj, root, output / "conditioning")
        conditioning = ConditioningCrop(
            uri=key.uri,
            sha256=key.sha256,
            source_photo_sha256=obj.photo.sha256,
            crop_hash=canonical_hash(obj.crop),
        )
        clip = obj.clip
        if clip is not None:
            local_file(root, clip)
            if clip.generated:
                assert clip.motion_recipe is not None
                native = json.loads(local_file(root, clip.motion_recipe).read_text())
                if (
                    canonical_hash(native) != clip.motion_recipe_hash
                    or native["spec"]["image_sha256"] != key.sha256
                ):
                    raise ValueError("Cached footage differs from its stored conditioning")
        else:
            prompt_dir = Path(__file__).parents[1] / "prompts"
            prompt = (
                (prompt_dir / "motion_source.md").read_text().replace("{{observed}}", obj.observed)
            )
            image = f"data/catalog-motion/{key.sha256}.jpg"
            spec = PreviewSpec(
                revision=REVISION,
                image=image,
                image_sha256=key.sha256,
                prompt=prompt,
                negative_prompt=(prompt_dir / "motion_negative.md").read_text(),
                seeds=[seed + index],
                width=576,
                height=1024,
                frames=61,
                fps=12,
                steps=40,
                guidance=5,
                shift=3,
            )
            identity = canonical_hash(spec)
            remote = f"outputs/catalog-motion/{identity}"
            directory = output / identity
            directory.mkdir(parents=True, exist_ok=True)
            spec_file = directory / "spec.json"
            spec_file.write_text(spec.model_dump_json(indent=2) + "\n")

            def status(remote_directory: str = remote) -> MotionStatus:
                return MotionStatus.model_validate_json(
                    tx.run(
                        [
                            python,
                            "-m",
                            "gpu_worker.catalog_motion",
                            "status",
                            "--directory",
                            remote_directory,
                        ]
                    )
                )

            state = status()
            if state.state == "missing":
                # Do not contend with a caption model or another user's GPU work.
                memory = tx.run(
                    [
                        "/usr/lib/wsl/lib/nvidia-smi",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ]
                )
                if int(memory.strip()) > 2000:
                    raise RuntimeError(
                        "GPU is busy; unload the caption model before animating photos"
                    )
                tx.run(["mkdir", "-p", remote, "data/catalog-motion"])
                tx.upload(local_file(root, key), image)
                tx.upload(spec_file, f"{remote}/spec.json")
                tx.run(
                    [
                        "tmux",
                        "new-session",
                        "-d",
                        "-s",
                        f"instabay-motion-{identity[:12]}",
                        shlex.join(
                            [
                                "env",
                                "INSTABAY_GPU_ENABLED=1",
                                python,
                                "-m",
                                "gpu_worker.catalog_motion",
                                "run",
                                "--directory",
                                remote,
                            ]
                        ),
                    ]
                )
            while state.state != "complete":
                if state.state == "failed":
                    raise RuntimeError("Motion failed; reconcile its stored receipt before retry")
                if (time.monotonic() - started) / 60 > max_minutes:
                    raise TimeoutError("Motion budget elapsed; remote receipt retained for resume")
                time.sleep(2)
                state = status()
            tx.download(f"{remote}/receipt.json", directory / "receipt.json")
            receipt = MotionReceipt.model_validate_json((directory / "receipt.json").read_bytes())
            native_directory = receipt.directory
            tx.download(f"{native_directory}/recipe.json", directory / "recipe.json")
            tx.download(f"{native_directory}/result.json", directory / "result.json")
            result = MotionCapture.model_validate_json((directory / "result.json").read_bytes())
            raw_recipe = json.loads((directory / "recipe.json").read_text())
            native = NativeMotionRecipe.model_validate(raw_recipe)
            if (
                canonical_hash(raw_recipe) != receipt.recipe_hash
                or result.recipe_hash != receipt.recipe_hash
                or native.spec != spec
                or result.recipe_file_sha256 != digest(directory / "recipe.json")
                or len(result.clips) != 1
                or result.clips[0].file != f"{native_directory}/shot-0.mp4"
            ):
                raise ValueError("Native job does not match the requested source/settings")
            tx.download(result.clips[0].file, directory / "clip.mp4")
            if digest(directory / "clip.mp4") != result.clips[0].sha256:
                raise ValueError("Native footage bytes differ")
            info = probe(directory / "clip.mp4")
            video = next(s for s in info["streams"] if s.get("codec_type") == "video")
            if (
                video.get("width") != spec.width
                or video.get("height") != spec.height
                or float(info["format"]["duration"]) < 5
            ):
                raise ValueError("Native clip cannot cover the expected scenic scene")
            clip = SourceClip(
                uri=(directory / "clip.mp4").relative_to(root).as_posix(),
                sha256=digest(directory / "clip.mp4"),
                generated=True,
                reference_only=True,
                credit=obj.attribution,
                motion_recipe=FileRef(
                    uri=(directory / "recipe.json").relative_to(root).as_posix(),
                    sha256=digest(directory / "recipe.json"),
                ),
                motion_recipe_hash=receipt.recipe_hash,
                start_s=0,
            )
        objects.append(obj.model_copy(update={"clip": clip, "conditioning": conditioning}))
        current = catalog.model_copy(update={"objects": objects + catalog.objects[index + 1 :]})
        (output / "catalog.partial.json").write_text(current.model_dump_json(indent=2) + "\n")
    final = ObjectCatalog.model_validate(
        catalog.model_copy(update={"objects": objects}).model_dump()
    )
    (output / "catalog.json").write_text(final.model_dump_json(indent=2) + "\n")
    return final
