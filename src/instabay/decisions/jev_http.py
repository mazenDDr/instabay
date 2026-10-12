"""FR-08, NFR-04: HUMAN-invoked /v1/systemone client; fake/MockTransport tests stay offline."""

import os
from urllib.parse import urlsplit

import httpx
from pydantic import Field, JsonValue, model_validator

from instabay.core.schemas import Boundary, canonical_hash
from instabay.decisions.engine import Answer, DecisionUnavailableError, Question, normalize_answers


class SystemOneConfig(Boundary):
    """FR-08: endpoint/model revisions are explicit; no unverified 'latest' model default."""

    base_url: str
    revision: str = Field(min_length=1)
    model: str | None = None
    timeout_s: float = Field(default=30, gt=0, le=60)
    max_state_chars: int = Field(default=50000, ge=1, le=50000)

    @model_validator(mode="after")
    def endpoint(self) -> "SystemOneConfig":
        p = urlsplit(self.base_url)
        if p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
            raise ValueError("Endpoint must be a bare origin without credentials")
        if p.scheme != "https" and not (
            p.scheme == "http"
            and p.hostname in {"100.109.90.64", "gpu-box", "127.0.0.1", "localhost"}
        ):
            raise ValueError("HTTP is allowed only for the configured Tailscale/loopback service")
        if not p.hostname:
            raise ValueError("Endpoint needs a hostname")
        if p.hostname == "api.typesafe.ai" and (
            self.model is None or self.model.endswith(("-latest", "-preview"))
        ):
            raise ValueError("HUMAN: pin and verify a supported hosted model version")
        return self


class SystemOneHTTPEngine:
    """FR-08: same client for laya-serve or Jev; failures never disclose keys/provider text."""

    synthetic = False

    def __init__(
        self,
        config: SystemOneConfig,
        *,
        confirm_external: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config, self.confirm_external = config, confirm_external
        self.engine_id = "http-systemone:" + canonical_hash(config)
        self.client = httpx.Client(
            timeout=config.timeout_s, follow_redirects=False, trust_env=False, transport=transport
        )

    def decide(
        self, state: str | dict[str, JsonValue], questions: dict[str, Question]
    ) -> dict[str, Answer]:
        if not self.confirm_external or os.environ.get("INSTABAY_DECISIONS_ENABLED") != "1":
            raise DecisionUnavailableError("HUMAN: explicitly enable external decision requests")
        token = os.environ.get("INSTABAY_SYSTEMONE_API_KEY", "")
        p = urlsplit(self.config.base_url)
        if p.scheme == "https" and not token.strip():
            raise DecisionUnavailableError("HUMAN: set the System One API key in ignored .env")
        if p.scheme == "http" and token:
            raise DecisionUnavailableError(
                "Do not send a hosted credential to the local HTTP service"
            )
        payload = {"state": state, "questions": {k: v.wire() for k, v in questions.items()}}
        if self.config.model is not None:
            payload["model"] = self.config.model
        if len(str(state)) > self.config.max_state_chars:
            raise DecisionUnavailableError("Decision state exceeds configured input limit")
        try:
            response = self.client.post(
                self.config.base_url.rstrip("/") + "/v1/systemone",
                json=payload,
                headers={"Authorization": "Bearer " + token} if token else {},
            )
            if response.status_code != 200:
                raise DecisionUnavailableError(
                    f"System One request rejected (HTTP {response.status_code})"
                )
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise DecisionUnavailableError("System One HTTP/JSON failure") from None
        return normalize_answers(body, questions)

    def close(self) -> None:
        """NFR-06: release HTTP connections after HUMAN-run evaluation."""
        self.client.close()
