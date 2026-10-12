"""FR-04, NFR-04: production transport is offline-testable and never uses canned fallback."""

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from instabay.adapters.fake_llm import FakeLLM
from instabay.adapters.llm import CompletionRequest
from instabay.adapters.native_llm import NativeLLMClient
from instabay.core.fixture_schemas import CopyFixture
from instabay.db import SQLiteCallStore
from instabay.llm import LLMService

MODEL = "Qwen/test@" + "a" * 40


def request() -> CompletionRequest:
    return CompletionRequest(
        template_name="copy_en",
        slot_id="fixture",
        model=MODEL,
        prompt="fixture",
        prompt_hash="0" * 64,
        inputs={},
        output_schema={},
        temperature=0,
        max_output_tokens=128,
    )


def test_opt_in_refuses_before_http() -> None:
    client = NativeLLMClient(
        "http://127.0.0.1:18765",
        MODEL,
        transport=httpx.MockTransport(lambda _: pytest.fail("HTTP")),
    )
    with pytest.raises(PermissionError):
        client.complete(request())
    client.close()


@pytest.mark.parametrize(
    "origin",
    [
        "https://external.example",
        "http://gpu-box/path",
        "http://user:pass@gpu-box",  # pragma: allowlist secret - invalid synthetic test URL
    ],
)
def test_private_origin_only(origin: str) -> None:
    with pytest.raises(ValueError):
        NativeLLMClient(origin, MODEL)


@pytest.mark.parametrize("outcome", ["ok", "wrong_model", "missing_usage", "provider_error"])
def test_real_response_boundary_and_sanitized_failure(monkeypatch, outcome: str) -> None:
    monkeypatch.setenv("INSTABAY_LLM_ENABLED", "1")

    def transport(req):
        assert req.url.path == "/generate"
        if outcome == "provider_error":
            return httpx.Response(503, json={"detail": "synthetic-private-error"})
        body = {
            "model": "other" if outcome == "wrong_model" else MODEL,
            "output_json": "{}",
            "input_tokens": 20,
            "output_tokens": 5,
            "cost_usd": 0,
            "latency_ms": 12,
        }
        if outcome == "missing_usage":
            del body["output_tokens"]
        return httpx.Response(200, json=body)

    client = NativeLLMClient(
        "http://127.0.0.1:18765",
        MODEL,
        confirm_external=True,
        transport=httpx.MockTransport(transport),
    )
    if outcome == "ok":
        assert client.complete(request()).input_tokens == 20
    else:
        with pytest.raises(RuntimeError, match="no fixture fallback") as error:
            client.complete(request())
        assert "synthetic-private-error" not in str(error.value)
    client.close()


def test_configured_model_changes_logged_cache_identity(tmp_path: Path) -> None:
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        fake = FakeLLM(Path("tests/fixtures/llm"))
        service = LLMService(fake, store, model_overrides={"copy_en": "configured-model"})
        service.generate(
            template_name="copy_en", slot_id="wk42-tue-1", inputs={}, output_type=CopyFixture
        )
        assert (
            store.calls()[0].model != "configured-model"
        )  # Fixture completion truth is preserved.
        # Request model changes the cache key even if an adapter supplies the same canned output.
        original = store.calls()[0].cache_key
        LLMService(fake, store).generate(
            template_name="copy_en", slot_id="wk42-tue-1", inputs={}, output_type=CopyFixture
        )
        assert store.calls()[1].cache_key != original and store.calls()[1].status != "cached"


def test_preview_requires_confirmation_before_client(monkeypatch) -> None:
    import instabay.generation_commands as generation
    from instabay.cli import app

    monkeypatch.setattr(generation, "NativeLLMClient", lambda *a, **kw: pytest.fail("client"))
    result = CliRunner().invoke(app, ["generate-preview", "--model", MODEL])
    assert result.exit_code == 2 and "--confirm-generation" in result.output


@pytest.mark.parametrize("arabic_valid", [True, False])
def test_preview_two_stages_log_cache_and_never_write_failed_copy(
    tmp_path: Path, monkeypatch, arabic_valid: bool
) -> None:
    import json

    import instabay.generation_commands as generation
    from instabay.cli import app

    monkeypatch.setenv("INSTABAY_LLM_ENABLED", "1")
    stages = []

    def transport(req):
        body = json.loads(req.content)
        stages.append(body)
        if "english" in body["inputs"]:
            output = (
                {
                    "caption": "أقواس ونخيل.",
                    "alt_text": "سقف خشبي.",
                    "overlays": ["هدوء", "نخيل", "ضوء"],
                }
                if arabic_valid
                else {"caption": None}
            )
        else:
            output = {
                "en": {"caption": "Daylight through the arcade.", "alt_text": "A wooden ceiling."},
                "ar": {"caption": "نص أولي.", "alt_text": "وصف أولي."},
                "overlays": [{"en": "Daylight.", "ar": "ضوء."}] * 3,
            }
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "output_json": json.dumps(output),
                "input_tokens": 20,
                "output_tokens": 10,
                "cost_usd": 0,
            },
        )

    monkeypatch.setattr(
        generation,
        "NativeLLMClient",
        lambda origin, model, **kw: NativeLLMClient(
            origin, model, **kw, transport=httpx.MockTransport(transport)
        ),
    )
    options = [
        "generate-preview",
        "--model",
        MODEL,
        "--confirm-generation",
        "--output",
        str(tmp_path / "copy.json"),
        "--db",
        str(tmp_path / "calls.sqlite"),
    ]
    result = CliRunner().invoke(app, options)
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        assert [c.template_name for c in store.calls()] == [
            "resort_preview",
            "resort_preview_ar",
        ] + ([] if arabic_valid else ["resort_preview_ar"])
    if not arabic_valid:
        assert result.exit_code != 0 and not (tmp_path / "copy.json").exists()
        return
    assert result.exit_code == 0, result.output
    copy = generation.ReelCopy.model_validate_json((tmp_path / "copy.json").read_bytes())
    assert copy.en.caption == "Daylight through the arcade." and copy.ar.caption == "أقواس ونخيل."
    assert len(stages) == 2
    replay = CliRunner().invoke(app, options)
    assert replay.exit_code == 0 and len(stages) == 2
    metadata = json.loads((tmp_path / "generation.json").read_text())
    assert metadata["usage"]["calls"] == 0 and metadata["reference_only"]
    assert {s["status"] for s in metadata["stages"]} == {"cached"}
