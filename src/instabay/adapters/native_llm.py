"""FR-04, NFR-04: schema-bound real generation behind the established LLMClient protocol."""

import base64
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from instabay.adapters.llm import Completion, CompletionRequest, ImageInput


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
        self.failure_stage: str | None = None
        self.client = httpx.Client(
            base_url=origin,
            timeout=180,
            transport=transport,
            trust_env=False,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    @staticmethod
    def _image(image: ImageInput) -> str:
        """NFR-03: send only the exact bytes the request (and its cache key) names."""
        data = Path(image.uri).read_bytes()
        if hashlib.sha256(data).hexdigest() != image.sha256:
            raise ValueError("Image bytes differ from the request")
        return base64.b64encode(data).decode("ascii")

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
            self.failure_stage = "transport"
            payload = request.model_dump(
                mode="json", exclude={"template_name", "slot_id", "prompt_hash", "images"}
            )
            if request.images:
                self.failure_stage = "image_bytes"
                payload["images"] = [
                    {"id": image.id, "data": self._image(image)} for image in request.images
                ]
                self.failure_stage = "transport"
            response = self.client.post("/generate", json=payload)
            self.failure_stage = f"http_{response.status_code}"
            response.raise_for_status()
            self.failure_stage = "response_schema"
            raw = response.json()
            result = Completion.model_validate({k: raw[k] for k in Completion.model_fields})
            if result.model != self.model:
                raise ValueError("Returned model identity differs")
            self.last_completion = result
            self.failure_stage = None
            return result
        except Exception:
            raise RuntimeError(
                f"Native generation failed at {self.failure_stage}; no fixture fallback was used"
            ) from None
