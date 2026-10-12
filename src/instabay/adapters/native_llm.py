"""FR-04, NFR-04: schema-bound real generation behind the established LLMClient protocol."""

import os
import re
from urllib.parse import urlsplit

import httpx

from instabay.adapters.llm import Completion, CompletionRequest


class NativeLLMClient:
    """NFR-05: explicitly configured private Qwen server; never falls back to canned answers."""

    def __init__(
        self,
        origin: str,
        model: str,
        *,
        confirm_external: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "gpu-box", "100.109.90.64"}
            or parsed.path
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Native LLM must use a private loopback/Tailscale origin")
        if not re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", model):
            raise ValueError("Native model must include its exact revision")
        self.model, self.confirm_external = model, confirm_external
        self.last_completion: Completion | None = None
        self.client = httpx.Client(
            base_url=origin, timeout=180, transport=transport, trust_env=False
        )

    def close(self) -> None:
        """NFR-06: release transport resources."""
        self.client.close()

    def complete(self, request: CompletionRequest) -> Completion:
        """NFR-06: preserve actual usage and reject unexpected identity or raw error leakage."""
        if not self.confirm_external or os.environ.get("INSTABAY_LLM_ENABLED") != "1":
            raise PermissionError("Native LLM needs explicit generation opt-in")
        if request.model != self.model:
            raise ValueError("Request/cache model differs from the native model")
        try:
            response = self.client.post(
                "/generate",
                json=request.model_dump(
                    mode="json", exclude={"template_name", "slot_id", "prompt_hash"}
                ),
            )
            response.raise_for_status()
            raw = response.json()
            result = Completion.model_validate({k: raw[k] for k in Completion.model_fields})
            if result.model != self.model:
                raise ValueError("Returned model identity differs")
            self.last_completion = result
            return result
        except Exception:
            raise RuntimeError("Native generation failed; no fixture fallback was used") from None
