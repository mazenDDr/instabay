"""FR-07, FR-10, NFR-04: HUMAN-invoked native HTTP; tests inject httpx.MockTransport."""

import hashlib
import os
import re
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

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
from instabay.adapters.graph_transport import GraphResponse, GraphTransport
from instabay.core.schemas import MediaManifest


def require_live(confirm_live: bool) -> None:
    """FR-09: fake transports need the same explicit mode/confirmation as native ones."""
    if os.environ.get("INSTABAY_MODE", "dry_run") != "live" or not confirm_live:
        raise LiveConfigurationError("Live requests require INSTABAY_MODE=live and --confirm-live")


class HttpxGraphTransport:
    """NFR-04: bearer header only; no tokens in URLs, journals or exception messages."""

    def __init__(
        self,
        config: GraphConfig,
        credentials: GraphCredentials,
        *,
        confirm_live: bool,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        require_live(confirm_live)
        if GraphCredentials.from_env() != credentials:
            raise LiveConfigurationError("Native credentials must match the current environment")
        self.config, self.credentials, self.confirm_live = config, credentials, confirm_live
        self.client = httpx.Client(
            timeout=config.request_timeout_s,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def request(
        self, method: Literal["GET", "POST"], path: str, params: dict[str, str]
    ) -> GraphResponse:
        require_live(self.confirm_live)
        if GraphCredentials.from_env() != self.credentials:
            raise LiveConfigurationError("Native credentials changed; recreate the adapter")
        if not re.fullmatch(r"/[0-9]+(?:/[a-z_]+)?", path):
            raise GraphProtocolError("Graph path is not a supported resource path")
        if any("token" in key.lower() for key in params):
            raise GraphProtocolError("Credentials are forbidden in request parameters")
        try:
            response = self.client.request(
                method,
                self.config.base_url + path,
                params=params if method == "GET" else None,
                data=params if method == "POST" else None,
                headers={
                    "Authorization": "Bearer " + self.credentials.access_token.get_secret_value()
                },
            )
            hint = response.headers.get("retry-after", "")
            retry_after = float(hint) if hint.isdigit() else None
            return GraphResponse(
                status_code=response.status_code, body=response.json(), retry_after_s=retry_after
            )
        except httpx.HTTPError:
            raise GraphTransportError("Graph HTTP failed; remote outcome may be unknown") from None
        except (ValueError, ValidationError):
            raise GraphProtocolError("Graph returned unsupported JSON") from None

    def close(self) -> None:
        """NFR-06: release sockets when the HUMAN command finishes."""
        self.client.close()


def graph_request(
    transport: GraphTransport, method: Literal["GET", "POST"], path: str, params: dict[str, str]
) -> dict[str, object]:
    """FR-10: numeric errors only; HTTP 5xx remains ambiguous for mutating requests."""
    response = transport.request(method, path, params)
    error = response.body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    subcode = error.get("error_subcode") if isinstance(error, dict) else None
    if response.status_code == 429 or (isinstance(code, int) and code in {4, 17, 32, 613, 80004}):
        raise GraphRateLimitError(response.retry_after_s)
    if response.status_code >= 500:
        raise GraphTransportError("Graph server error; remote outcome may be unknown")
    if error is not None or response.status_code >= 400:
        raise GraphAPIError(
            code if isinstance(code, int) else response.status_code,
            subcode if isinstance(subcode, int) else None,
        )
    if response.status_code != 200:
        raise GraphProtocolError("Graph returned an unsupported HTTP status")
    return dict(response.body)


class MediaVerifier(Protocol):
    """NFR-05: verify approved bytes before container creation, behind an injectable boundary."""

    def verify(self, manifest: MediaManifest, config: GraphConfig) -> None: ...


class StubMediaVerifier:
    """NFR-07: offline synthetic media verification; never selects itself in native commands."""

    def verify(self, manifest: MediaManifest, config: GraphConfig) -> None:
        validate_media(manifest, config)


def validate_media(manifest: MediaManifest, config: GraphConfig) -> None:
    """FR-07: fail closed on reference assets, non-approved hosts and excessive sizes."""
    if manifest.reference_only:
        raise MediaValidationError("Reference-only resort photos cannot be live published")
    if manifest.render_recipe and manifest.render_recipe.get("backend") in {
        "stub",
        "synthetic_fixture",
    }:
        raise MediaValidationError("Stub renders cannot be live published")
    for asset in [*manifest.assets, *([manifest.cover] if manifest.cover else [])]:
        if (urlsplit(asset.url).hostname or "").lower() not in config.media_hosts:
            raise MediaValidationError("HUMAN: allow this public media host in Graph configuration")
        cap = config.image_max_bytes if asset.kind == "image" else config.video_max_bytes
        if asset.size_bytes > cap:
            raise MediaValidationError("Media exceeds the configured conservative size cap")


class HttpxMediaVerifier:
    """FR-07: bounded public HTTP 200 stream must match approved size, MIME and SHA-256."""

    def __init__(
        self, config: GraphConfig, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.client = httpx.Client(
            timeout=config.request_timeout_s,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def verify(self, manifest: MediaManifest, config: GraphConfig) -> None:
        validate_media(manifest, config)
        for asset in [*manifest.assets, *([manifest.cover] if manifest.cover else [])]:
            digest, count = hashlib.sha256(), 0
            try:
                with self.client.stream(
                    "GET", asset.url, headers={"Accept-Encoding": "identity"}
                ) as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("content-type", "").split(";")[0] != asset.mime_type
                    ):
                        raise MediaValidationError(
                            "Public media did not return HTTP 200 and the approved MIME type"
                        )
                    for chunk in response.iter_bytes(chunk_size=65536):
                        count += len(chunk)
                        if count > asset.size_bytes:
                            raise MediaValidationError(
                                "Public media exceeds its approved byte size"
                            )
                        digest.update(chunk)
            except httpx.HTTPError:
                raise MediaValidationError("Public media verification failed") from None
            if count != asset.size_bytes or digest.hexdigest() != asset.content_sha256:
                raise MediaValidationError("Public media differs from the approved content hash")

    def close(self) -> None:
        """NFR-06: release HTTP connections after media verification."""
        self.client.close()
