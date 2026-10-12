"""FR-07, FR-09 to FR-11: typed Graph configuration, media and remote-operation boundaries."""

import os
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, SecretStr

from instabay.core.schemas import Boundary, Hash, UTCDateTime

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
