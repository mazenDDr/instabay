"""FR-08: native adapters tested with synthetic HTTP and fake optional modules, no GPU/network."""

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from instabay.decisions.engine import DecisionProtocolError, DecisionUnavailableError, Question
from instabay.decisions.jev_http import SystemOneConfig, SystemOneHTTPEngine
from instabay.decisions.laya_local import LayaLocalEngine


@pytest.mark.parametrize("host", ["http://100.109.90.64:8000", "https://api.typesafe.ai"])
def test_systemone_wire_bearer_only_and_noul_normalization(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTABAY_DECISIONS_ENABLED", "1")
    if host.startswith("https"):
        monkeypatch.setenv("INSTABAY_SYSTEMONE_API_KEY", "synthetic-systemone-sentinel")
    else:
        monkeypatch.delenv("INSTABAY_SYSTEMONE_API_KEY", raising=False)

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/systemone"
        assert "sentinel" not in str(request.url) and "sentinel" not in request.content.decode()
        assert ("authorization" in request.headers) == host.startswith("https")
        return httpx.Response(
            200,
            json={
                "answers": {"safe": {"type": "noul", "noul": 0.02}},
                "usage": {"input_tokens": 10},
            },
        )

    engine = SystemOneHTTPEngine(
        SystemOneConfig(
            base_url=host, revision="synthetic-contract-v1", model="synthetic-pinned-model"
        ),
        confirm_external=True,
        transport=httpx.MockTransport(handle),
    )
    try:
        assert (
            engine.decide("fixture", {"safe": Question(type="noul", instructions="fixture")})[
                "safe"
            ].confidence
            == 0.98
        )
    finally:
        engine.close()


@pytest.mark.parametrize("failure", ["disabled", "key_missing", "rate", "malformed", "timeout"])
def test_http_failure_no_private_provider_text(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSTABAY_DECISIONS_ENABLED", "0" if failure == "disabled" else "1")
    if failure == "key_missing":
        monkeypatch.delenv("INSTABAY_SYSTEMONE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("INSTABAY_SYSTEMONE_API_KEY", "synthetic-systemone-sentinel")

    def handle(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic-systemone-sentinel")
        return (
            httpx.Response(429, json={"message": "synthetic-systemone-sentinel"})
            if failure == "rate"
            else httpx.Response(200, text="synthetic-systemone-sentinel")
        )

    engine = SystemOneHTTPEngine(
        SystemOneConfig(
            base_url="https://api.typesafe.ai", revision="synthetic", model="synthetic-pinned-model"
        ),
        confirm_external=True,
        transport=httpx.MockTransport(handle),
    )
    try:
        with pytest.raises(DecisionUnavailableError) as error:
            engine.decide("fixture", {"safe": Question(type="noul", instructions="fixture")})
        assert "sentinel" not in str(error.value)
    finally:
        engine.close()


def test_laya_guarded_import_lazy_cuda_router_and_missing_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from instabay.decisions import laya_local

    models = {name: tmp_path / name for name in ("english", "multilingual")}
    for p in models.values():
        p.mkdir()
    engine = LayaLocalEngine(revision="fixture", models=models, confirm_gpu=True)
    assert engine.router is None
    monkeypatch.setenv("INSTABAY_DECISIONS_ENABLED", "1")
    monkeypatch.setattr(laya_local.platform, "system", lambda: "Linux")

    def unavailable(name: str):
        raise ImportError("synthetic-private-error")

    monkeypatch.setattr(laya_local.importlib, "import_module", unavailable)
    with pytest.raises(DecisionUnavailableError) as error:
        engine.decide("fixture", {"safe": Question(type="noul", instructions="fixture")})
    assert "private" not in str(error.value)
    created = []

    class Router:
        def __init__(self, **kwargs):
            created.append(kwargs)
            assert (
                kwargs["device"] == "cuda" and kwargs["max_loaded"] == 1 and not kwargs["preload"]
            )

        def predict(self, state, questions):
            return {"answers": {"safe": {"noul": 0.1, "confidence": 0.9}}}

    monkeypatch.setattr(
        laya_local.importlib, "import_module", lambda _: SimpleNamespace(Router=Router)
    )
    assert (
        engine.decide("fixture", {"safe": Question(type="noul", instructions="fixture")})[
            "safe"
        ].noul
        == 0.1
    )
    engine.decide("fixture", {"safe": Question(type="noul", instructions="fixture")})
    assert len(created) == 1
    monkeypatch.setattr(laya_local.platform, "system", lambda: "Darwin")
    with pytest.raises(DecisionUnavailableError):
        engine.decide("fixture", {"safe": Question(type="noul", instructions="fixture")})
    assert "torch" not in sys.modules


def test_unsupported_primitive_and_boolean_confidence_are_rejected() -> None:
    from instabay.decisions.engine import normalize_answers

    for value in (
        {"type": "choice", "noul": 0.2, "confidence": 0.9},
        {"noul": False, "confidence": 0.9},
        {"noul": 0.2, "confidence": True},
    ):
        with pytest.raises(DecisionProtocolError):
            normalize_answers(
                {"answers": {"safe": value}},
                {"safe": Question(type="noul", instructions="fixture")},
            )
    assert normalize_answers(
        {"answers": {"safe": {"noul": 0.2, "confidence": 0.9, "action": "abstain"}}},
        {"safe": Question(type="noul", instructions="fixture")},
    )["safe"].abstained
