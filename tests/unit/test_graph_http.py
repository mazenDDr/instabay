"""NFR-04, NFR-07: native HTTP contracts use MockTransport and synthetic sentinels only."""

import httpx
import pytest

from instabay.adapters.graph_http import HttpxGraphTransport, HttpxMediaVerifier, graph_request
from instabay.adapters.graph_models import (
    GraphAPIError,
    GraphConfig,
    GraphCredentials,
    GraphProtocolError,
    GraphRateLimitError,
    GraphTransportError,
    LiveConfigurationError,
    MediaValidationError,
)
from tests.graph_support import GRAPH_CONFIG, media


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> GraphCredentials:
    monkeypatch.setenv("INSTABAY_MODE", "live")
    monkeypatch.setenv("INSTAGRAM_USER_ID", "1000")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "synthetic-header-sentinel")
    return GraphCredentials.from_env()


@pytest.mark.parametrize(
    "login,host", [("instagram", "graph.instagram.com"), ("facebook", "graph.facebook.com")]
)
def test_native_bearer_not_in_url_form_repr_or_serialization(
    credentials: GraphCredentials, login: str, host: str
) -> None:
    config = GraphConfig.model_validate({"login": login})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == host and request.url.path == "/v25.0/1000/media_publish"
        assert request.headers["Authorization"] == "Bearer synthetic-header-sentinel"
        assert "sentinel" not in str(request.url) and "sentinel" not in request.content.decode()
        assert request.content == b"creation_id=2000"
        return httpx.Response(200, json={"id": "3000"})

    adapter = HttpxGraphTransport(
        config, credentials, confirm_live=True, transport=httpx.MockTransport(handler)
    )
    try:
        assert graph_request(adapter, "POST", "/1000/media_publish", {"creation_id": "2000"}) == {
            "id": "3000"
        }
        assert "sentinel" not in repr(credentials) + credentials.model_dump_json()
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "status,body,error",
    [
        (429, {"error": {"code": 4, "message": "synthetic-header-sentinel"}}, GraphRateLimitError),
        (
            400,
            {"error": {"code": 190, "error_subcode": 463, "message": "synthetic-header-sentinel"}},
            GraphAPIError,
        ),
        (503, {"error": {"code": 2, "message": "synthetic-header-sentinel"}}, GraphTransportError),
        (400, {"error": {"code": {"bad": "synthetic-header-sentinel"}}}, GraphAPIError),
    ],
)
def test_api_failures_are_sanitized_no_provider_text(
    credentials: GraphCredentials, status: int, body: dict, error: type[Exception]
) -> None:
    adapter = HttpxGraphTransport(
        GRAPH_CONFIG,
        credentials,
        confirm_live=True,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json=body, headers={"retry-after": "45"})
        ),
    )
    try:
        with pytest.raises(error) as caught:
            graph_request(adapter, "GET", "/2000", {})
        assert "sentinel" not in str(caught.value)
        if isinstance(caught.value, GraphRateLimitError):
            assert caught.value.retry_after_s == 45
    finally:
        adapter.close()


@pytest.mark.parametrize("kind", ["html", "timeout"])
def test_malformed_and_network_failures_do_not_echo_response_or_request(
    credentials: GraphCredentials, kind: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic-header-sentinel", request=request)
        return httpx.Response(200, text="synthetic-header-sentinel")

    adapter = HttpxGraphTransport(
        GRAPH_CONFIG, credentials, confirm_live=True, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises((GraphProtocolError, GraphTransportError)) as caught:
            adapter.request("GET", "/2000", {})
        assert "sentinel" not in str(caught.value) and caught.value.__suppress_context__
    finally:
        adapter.close()


def test_native_rechecks_mode_and_credentials_before_every_request(
    credentials: GraphCredentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("No request allowed")

    adapter = HttpxGraphTransport(
        GRAPH_CONFIG, credentials, confirm_live=True, transport=httpx.MockTransport(forbidden)
    )
    try:
        monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN")
        with pytest.raises(LiveConfigurationError):
            adapter.request("GET", "/2000", {})
        monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "synthetic-header-sentinel")
        monkeypatch.setenv("INSTABAY_MODE", "dry_run")
        with pytest.raises(LiveConfigurationError):
            adapter.request("GET", "/2000", {})
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "response,status,mime",
    [
        (b"jpeg", 200, "image/jpeg"),
        (b"evil", 200, "image/jpeg"),
        (b"jpeg", 302, "image/jpeg"),
        (b"jpeg", 200, "image/png"),
        (b"jpeg-more", 200, "image/jpeg"),
    ],
)
def test_media_verifier_public_200_mime_exact_size_and_hash(
    response: bytes, status: int, mime: str
) -> None:
    adapter = HttpxMediaVerifier(
        GRAPH_CONFIG,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, content=response, headers={"content-type": mime})
        ),
    )
    try:
        if (response, status, mime) == (b"jpeg", 200, "image/jpeg"):
            adapter.verify(media("photo"), GRAPH_CONFIG)
        else:
            with pytest.raises(MediaValidationError):
                adapter.verify(media("photo"), GRAPH_CONFIG)
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example.org/a.jpg",
        "https://127.0.0.1/a.jpg",
        "https://localhost/a.jpg",
        "https://cdn.example.org/a.jpg?token=secret",
        # Deliberately invalid synthetic Basic Auth URL.
        "https://user:secret@cdn.example.org/a.jpg",  # pragma: allowlist secret
    ],
)
def test_private_or_credentialed_media_urls_are_rejected(url: str) -> None:
    manifest = media("photo").model_dump()
    manifest["assets"][0]["url"] = url
    from instabay.core.schemas import MediaManifest

    with pytest.raises(ValueError):
        MediaManifest.model_validate(manifest)


def test_recipe_hash_tamper_and_stub_rejected() -> None:
    from instabay.adapters.graph_http import validate_media
    from instabay.core.schemas import MediaManifest, canonical_hash

    manifest = media("reel").model_dump()
    manifest["render_recipe"]["seed"] = 43
    with pytest.raises(ValueError):
        MediaManifest.model_validate(manifest)
    manifest["render_recipe"] = {"backend": "stub", "seed": 42}
    manifest["recipe_hash"] = canonical_hash(manifest["render_recipe"])
    with pytest.raises(MediaValidationError):
        validate_media(MediaManifest.model_validate(manifest), GRAPH_CONFIG)
