"""NFR-04, NFR-05: import-guarded native boundaries and recorded Comfy contracts."""

import json
from pathlib import Path

import httpx
import pytest

from instabay.core.recipe import RenderRecipe
from instabay.video.backends.base import ShotRecipe
from instabay.video.backends.comfyui import ComfyUIBackend
from instabay.video.backends.wan_diffusers import WanDiffusersBackend
from instabay.video.files import RenderError, digest
from instabay.video.keyframes import stub_recipe
from tests.unit.test_video_recipe import ROOT, shotlist


def native_recipe(root: Path, backend: str) -> RenderRecipe:
    data = stub_recipe(shotlist(), ROOT).model_dump(mode="json")
    data["backend"] = backend
    data["model"]["pipeline_class"] = "WanImageToVideoPipeline"
    for shot in data["shots"]["shots"]:
        shot["keyframe"]["source"] = "photo"
    checkpoint = root / "weights"
    checkpoint.mkdir(exist_ok=True)
    (checkpoint / "config.json").write_text("{}")
    data["model"]["weights"] = [
        {"uri": "weights/config.json", "sha256": digest(checkpoint / "config.json")}
    ]
    data["runtime"].update(
        docker_image_digest="sha256:" + "0" * 64,
        torch="fixture",
        cuda="fixture",
        driver="fixture",
        gpu="fixture",
    )
    if backend == "comfyui":
        keys = [
            "seed",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "frames",
            "steps",
            "cfg",
            "shift",
            "image",
        ]
        workflow = {
            "1": {"class_type": "SyntheticRecordedNode", "inputs": dict.fromkeys(keys, None)}
        }
        path = root / "workflow.json"
        path.write_text(json.dumps(workflow))
        data["model"]["workflow"] = {"uri": "workflow.json", "sha256": digest(path)}
        data["model"]["custom_nodes"] = {"SyntheticRecordedNode": "0" * 40}
        data["model"]["scheduler_config"] = {"bindings": {k: ["1", k] for k in keys}}
    return RenderRecipe.model_validate(data)


@pytest.mark.parametrize("backend", ["wan", "comfyui"])
def test_native_rejects_before_any_import_or_request(tmp_path: Path, backend: str) -> None:
    adapter = (
        WanDiffusersBackend()
        if backend == "wan"
        else ComfyUIBackend(transport=httpx.MockTransport(lambda _: pytest.fail("network")))
    )
    with pytest.raises(RenderError, match="HUMAN"):
        adapter.render_shot(
            ShotRecipe(recipe=native_recipe(tmp_path, backend), index=0), ROOT, tmp_path
        )
    if isinstance(adapter, ComfyUIBackend):
        adapter.close()


@pytest.mark.parametrize(
    "origin",
    [
        "https://public.example",
        "http://example.com",
        "http://gpu-box/path",
        "http://user:pass@gpu-box",  # pragma: allowlist secret - invalid synthetic test URL
    ],
)
def test_comfy_private_origin_only(origin: str) -> None:
    with pytest.raises(ValueError):
        ComfyUIBackend(origin)


@pytest.mark.parametrize(
    "outcome", ["complete", "error", "timeout", "missing_binding", "unsafe_output"]
)
def test_comfy_recorded_contract_validates_variables_and_bounded_poll(
    tmp_path: Path, monkeypatch, outcome: str
) -> None:
    monkeypatch.setattr("instabay.video.backends.comfyui.require_gpu", lambda *_: None)
    recipe = native_recipe(tmp_path, "comfyui")
    # This is a synthetic transport contract, never a GPU performance/quality measurement.
    calls = []

    def transport(request):
        calls.append(request.url.path)
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "fixture.ppm"})
        if request.url.path == "/prompt":
            body = json.loads(request.content)
            assert body["prompt"]["1"]["inputs"]["seed"] == 7
            assert body["prompt"]["1"]["inputs"]["frames"] == 150
            assert body["prompt"]["1"]["inputs"]["image"] == "fixture.ppm"
            return httpx.Response(
                200, json={"prompt_id": "fixture-job", "number": 1, "node_errors": {}}
            )
        if request.url.path == "/history/fixture-job":
            if outcome == "timeout":
                return httpx.Response(200, json={})
            return httpx.Response(
                200,
                json={
                    "fixture-job": {
                        "status": {"status_str": "error" if outcome == "error" else "success"},
                        "outputs": {
                            "1": {
                                "videos": [
                                    {
                                        "filename": "../escape.mp4"
                                        if outcome == "unsafe_output"
                                        else "fixture.mp4",
                                        "subfolder": "",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        if request.url.path == "/view":
            return httpx.Response(200, content=b"synthetic-MP4-contract-bytes")
        pytest.fail("unexpected route")

    if outcome == "missing_binding":
        data = recipe.model_dump()
        del data["model"]["scheduler_config"]["bindings"]["seed"]
        recipe = RenderRecipe.model_validate(data)
    # Inputs reside in two roots for the test; explicit resolver supplies immutable synthetic bytes.
    from instabay.video.files import local_file

    monkeypatch.setattr(
        "instabay.video.backends.comfyui.local_file",
        lambda root, ref: local_file(tmp_path if ref.uri == "workflow.json" else ROOT, ref),
    )
    adapter = ComfyUIBackend(
        confirm_gpu=True, transport=httpx.MockTransport(transport), max_polls=1, poll_seconds=0
    )
    if outcome == "complete":
        result = adapter.render_shot(ShotRecipe(recipe=recipe, index=0), tmp_path, tmp_path)
        assert Path(result.file).read_bytes() == b"synthetic-MP4-contract-bytes"
        assert calls == ["/upload/image", "/prompt", "/history/fixture-job", "/view"]
    else:
        with pytest.raises(RenderError):
            adapter.render_shot(ShotRecipe(recipe=recipe, index=0), tmp_path, tmp_path)
        assert "/view" not in calls
    adapter.close()
