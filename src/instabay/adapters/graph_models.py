"""FR-07, FR-09 to FR-11: typed Graph configuration, media and remote-operation boundaries."""

import ipaddress
import os
from typing import Annotated, Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, JsonValue, SecretStr, field_validator, model_validator

from instabay.core.schemas import Boundary, Hash, PostFormat, UTCDateTime, canonical_hash

GraphID = Annotated[str, Field(pattern=r"^[0-9]+$")]


class GraphConfig(Boundary):
    """FR-10: non-secret settings are configurable; SPEC facts awaiting HUMAN verification."""

    api_version: str = Field(default="v25.0", pattern=r"^v[0-9]+\.[0-9]+$")
    login: Literal["instagram", "facebook"] = "instagram"
    # HUMAN: verify supported API version, scopes and quota in your Meta app before live use.
    publish_cap: int = Field(default=50, ge=1, le=50)
    poll_interval_s: float = Field(default=60, ge=1, le=60)
    max_poll_checks: int = Field(default=6, ge=1, le=6)
    request_timeout_s: float = Field(default=30, gt=0, le=60)
    media_hosts: tuple[str, ...] = ()
    image_max_bytes: int = Field(default=8_000_000, ge=1, le=8_000_000)
    video_max_bytes: int = Field(default=300_000_000, ge=1, le=300_000_000)
    # Conservative SPEC cap; Meta's official example differs (1 GB). Do not claim latest truth.

    @property
    def base_url(self) -> str:
        host = "graph.instagram.com" if self.login == "instagram" else "graph.facebook.com"
        return f"https://{host}/{self.api_version}"


class GraphCredentials(Boundary):
    """NFR-04: credentials are read from the HUMAN-provided environment, never serialized."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    user_id: GraphID
    access_token: SecretStr = Field(repr=False, exclude=True)

    @classmethod
    def from_env(cls) -> Self:
        token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        user = os.environ.get("INSTAGRAM_USER_ID", "")
        if not token.strip() or not user.isdigit():
            raise LiveConfigurationError("HUMAN: set Instagram user ID and access token in .env")
        return cls(user_id=user, access_token=SecretStr(token))


class LiveConfigurationError(PermissionError):
    """NFR-04: dry-run defaults and explicit live confirmation are mandatory."""


class GraphTransportError(ConnectionError):
    """FR-10: sanitized network failure; a POST may have been accepted remotely."""


class GraphProtocolError(ValueError):
    """FR-10: unsupported/malformed Graph response, without raw provider text."""


class GraphAPIError(RuntimeError):
    """FR-10: only safe numeric error metadata survives provider response handling."""

    def __init__(self, code: int, subcode: int | None = None) -> None:
        self.code, self.subcode = code, subcode
        super().__init__(f"Graph API rejected the request (code={code}, subcode={subcode})")


class GraphRateLimitError(GraphAPIError):
    """FR-10: caller retries explicitly; accepted containers remain in the durable journal."""

    def __init__(self, retry_after_s: float | None = None) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(4)


class GraphContainerError(RuntimeError):
    """FR-10: ERROR/EXPIRED are terminal container outcomes, not success receipts."""


class GraphPendingError(RuntimeError):
    """FR-10: bounded polling stops; another invocation resumes the stored container."""


class GraphReconciliationRequired(RuntimeError):
    """FR-10: uncertain POSTs never get retried automatically or assigned invented IDs."""


class MediaValidationError(ValueError):
    """FR-07: approved URL bytes and declared media specifications must match."""


class MediaAsset(Boundary):
    """FR-07: HUMAN-verified metadata and public immutable bytes bound into approval."""

    url: str
    content_sha256: Hash
    kind: Literal["image", "video"]
    size_bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: Literal["image/jpeg", "video/mp4", "video/quicktime"]
    duration_s: float | None = Field(default=None, ge=3, le=900)
    fps: float | None = Field(default=None, ge=23, le=60)
    video_codec: Literal["h264", "hevc"] | None = None
    audio_codec: Literal["aac"] | None = None
    audio_sample_rate: int | None = Field(default=None, gt=0, le=48000)
    moov_at_front: bool = False

    @field_validator("url")
    @classmethod
    def public_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
            or host == "localhost"
            or host.endswith((".local", ".internal"))
        ):
            raise ValueError("Media needs a public HTTPS URL without credentials/query/fragment")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError("Media host must be a public domain") from None
        else:
            if not address.is_global:
                raise ValueError("Private/local media IPs are forbidden")
        return value

    @model_validator(mode="after")
    def media_spec(self) -> Self:
        if self.kind == "image":
            if self.mime_type != "image/jpeg" or not 0.8 <= self.width / self.height <= 1.91:
                raise ValueError("Images require JPEG and aspect ratio 4:5 to 1.91:1")
        elif (
            self.mime_type == "image/jpeg"
            or self.width > 1920
            or self.duration_s is None
            or self.fps is None
            or self.video_codec is None
            or self.audio_codec is None
            or self.audio_sample_rate is None
            or not self.moov_at_front
        ):
            raise ValueError("Video requires verified codecs, timing, dimensions and fast-start")
        return self


class MediaManifest(Boundary):
    """FR-07, NFR-03: included in the stored post hash before human approval."""

    format: PostFormat
    assets: list[MediaAsset] = Field(min_length=1, max_length=10)
    cover: MediaAsset | None = None
    reference_only: bool = True
    verified_by: str = Field(min_length=1)
    # HUMAN: verify bytes/specs/rights and facility fidelity before attaching this manifest.
    generated: bool = False
    recipe_hash: Hash | None = None
    render_recipe: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def format_spec(self) -> Self:
        count = len(self.assets)
        if self.format == "photo" and (count != 1 or self.assets[0].kind != "image"):
            raise ValueError("Photo requires one image")
        if self.format == "carousel" and (
            not 2 <= count <= 10 or any(a.kind != "image" for a in self.assets)
        ):
            raise ValueError("This carousel adapter supports 2-10 images")
        if self.format == "reel":
            if count != 1 or self.assets[0].kind != "video":
                raise ValueError("Reel requires one video")
            if self.render_recipe is None or self.recipe_hash != canonical_hash(
                cast(dict[str, object], self.render_recipe)
            ):
                raise ValueError("Reel needs a stored recipe with its exact canonical hash")
        if self.cover is not None and (self.format != "reel" or self.cover.kind != "image"):
            raise ValueError("Only reels may have an image cover")
        return self


class GraphJob(Boundary):
    """FR-10: durable state across crashes and retries; no tokens/raw errors persisted."""

    id: Hash
    post_id: str
    content_hash: Hash
    approval_id: str
    account_id: GraphID
    api_version: str
    login: Literal["instagram", "facebook"]
    payload_hash: Hash
    phase: Literal[
        "prepared", "creating", "processing", "ready", "publishing", "published", "error", "expired"
    ] = "prepared"
    child_ids: list[GraphID] = Field(default_factory=list)
    container_id: GraphID | None = None
    media_id: GraphID | None = None
    verified_media: bool = False
    last_status: str | None = None
    updated_at: UTCDateTime
    reconciliation_actor: str | None = None
    reconciliation_reason: str | None = None
