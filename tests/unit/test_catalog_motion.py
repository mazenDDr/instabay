"""FR-06, NFR-03: durable native requests remain photo-bound and private."""

import json
from shutil import copyfile

import pytest
from pydantic import ValidationError

from instabay.core.motion_capture import MotionReceipt, MotionStatus
from instabay.core.schemas import canonical_hash
from instabay.video.catalog_motion import animate_catalog
from instabay.video.direction import resolve_object
from instabay.video.files import command, digest
from tests.unit.test_content_evidence import ROOT, campaign


class Transport:
    def __init__(self, directory):
        self.directory = directory
        self.started = False
        self.files = {}
        self.memory = "500"
        self.launches = 0

    def run(self, args):
        if "--query-gpu=memory.used" in args:
            return self.memory
        if args[0] == "tmux":
            self.launches += 1
            self.started = True
        if "status" in args:
            if not self.started:
                return '{"state":"missing"}'
            return json.dumps({"state": "complete", "exit_code": 0, "receipt": self.receipt})
        return ""

    def upload(self, source, remote):
        if not remote.endswith("spec.json"):
            return
        spec = json.loads(source.read_text())
        native = {
            "kind": "experimental-wan-i2v-motion-v1",
            "spec": spec,
            "weights": {},
            "runtime": {"test": True},
            "pipeline_class": "WanImageToVideoPipeline",
            "expand_timesteps": True,
            "scheduler": {},
            "offload": "fixture",
            "vae": "fixture",
            "ai_disclosure": True,
            "reference_only": True,
            "determinism": "fixture",
        }
        identity = canonical_hash(native)
        folder = f"outputs/wan-motion/{identity}"
        self.receipt = {"recipe_hash": identity, "directory": folder}
        recipe = self.directory / "recipe.json"
        recipe.write_text(json.dumps(native, indent=2) + "\n")
        movie = self.directory / "fixture.mp4"
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=cyan:s=576x1024:r=12",
                "-frames:v",
                "61",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                str(movie),
            ]
        )
        result = {
            "recipe_hash": identity,
            "recipe_file_sha256": digest(recipe),
            "clips": [
                {
                    "file": folder + "/shot-0.mp4",
                    "sha256": digest(movie),
                    "seed": spec["seeds"][0],
                    "seconds": 1,
                }
            ],
            "seconds": 1,
            "peak_vram_bytes": 0,
            "ai_disclosure": True,
            "reference_only": True,
            "cost_usd_api_fees": 0,
            "quality_status": "synthetic transport test only",
        }
        result_file = self.directory / "result.json"
        result_file.write_text(json.dumps(result))
        receipt_file = self.directory / "receipt.json"
        receipt_file.write_text(json.dumps(self.receipt))
        self.files = {
            folder + "/recipe.json": recipe,
            folder + "/result.json": result_file,
            folder + "/shot-0.mp4": movie,
            remote.replace("spec.json", "receipt.json"): receipt_file,
        }

    def download(self, remote, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        copyfile(self.files[remote], target)


def test_photo_motion_binds_receipts_source_and_stored_conditioning(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTABAY_GPU_ENABLED", "1")
    monkeypatch.setattr("instabay.video.catalog_motion.time.sleep", lambda _: None)
    _, _, catalog, _ = campaign()
    catalog = catalog.model_copy(update={"objects": [catalog.get("shoreline")]})
    transport = Transport(tmp_path)
    output = ROOT / "outputs/tests-motion" / (tmp_path.parent.name + "-" + tmp_path.name)
    result = animate_catalog(catalog, ROOT, output, confirm_gpu=True, transport=transport)
    obj = result.objects[0]
    assert obj.clip.generated and obj.conditioning.source_photo_sha256 == obj.photo.sha256
    assert transport.launches == 1
    # Stored conditioning is reused even if the current crop encoder would produce different bytes.
    monkeypatch.setattr(
        "instabay.video.direction.command",
        lambda _: (_ for _ in ()).throw(AssertionError("reencoded")),
    )
    resolve_object(obj, ROOT, output / "unused")
    repeated = animate_catalog(result, ROOT, output, confirm_gpu=True, transport=transport)
    assert repeated == result and transport.launches == 1
    raw = obj.model_dump()
    raw["conditioning"]["source_photo_sha256"] = "a" * 64
    with pytest.raises(ValidationError, match="different source"):
        type(obj).model_validate(raw)


def test_busy_gpu_and_opt_out_do_not_launch(tmp_path, monkeypatch):
    _, _, catalog, _ = campaign()
    catalog = catalog.model_copy(update={"objects": [catalog.get("shoreline")]})
    transport = Transport(tmp_path)
    output = ROOT / "outputs/tests-motion" / (tmp_path.parent.name + "-" + tmp_path.name)
    with pytest.raises(PermissionError):
        animate_catalog(catalog, ROOT, output, confirm_gpu=False, transport=transport)
    monkeypatch.setenv("INSTABAY_GPU_ENABLED", "1")
    transport.memory = "9000"
    with pytest.raises(RuntimeError, match="GPU is busy"):
        animate_catalog(catalog, ROOT, output, confirm_gpu=True, transport=transport)
    assert transport.launches == 0
    with pytest.raises(ValueError, match="GPU-minute budget"):
        animate_catalog(catalog, ROOT, output, confirm_gpu=True, max_minutes=1, transport=transport)


def test_worker_receipt_cannot_download_unrelated_private_files():
    with pytest.raises(ValidationError):
        MotionReceipt(recipe_hash="a" * 64, directory="../../.env")
    with pytest.raises(ValidationError):
        MotionStatus(state="complete", exit_code=0)
