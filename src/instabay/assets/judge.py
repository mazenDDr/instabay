"""FR-08: a VLM looks at photos d3-flash was unsure about and picks a pillar with a reason.

The judge only sees the image and the brand's pillar descriptions. Its label is stored apart
from d3's and the owner's so each can be measured against owner corrections.
"""

import base64
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from instabay.core.schemas import Boundary
from instabay.decisions.vision import image_digest

VLM_MODEL = "Qwen/Qwen3.5-9B"


class Verdict(Boundary):
    """FR-08: one option from the request, or an abstention, plus a short visible reason."""

    choice: str | None
    reason: str = Field(max_length=500)


class PillarJudge(Protocol):
    judge_id: str

    def choose(self, image: Path, options: dict[str, str]) -> Verdict: ...


class FakePillarJudge:
    """NFR-07: answers keyed by exact image bytes; unknown images abstain."""

    judge_id = "fake-vlm-v1"

    def __init__(self, answers: dict[str, Verdict]) -> None:
        self.answers = answers
        self.calls = 0

    def choose(self, image: Path, options: dict[str, str]) -> Verdict:
        self.calls += 1
        verdict = self.answers.get(image_digest(image))
        if verdict is None or verdict.choice not in options:
            return Verdict(choice=None, reason="No synthetic verdict for this image")
        return verdict


class HTTPPillarJudge:
    """FR-08: HUMAN-enabled client for gpu_worker/vision_server.py `/v1/vlm-choice`."""

    def __init__(
        self,
        origin: str,
        *,
        confirm_external: bool = False,
        timeout_s: float = 300,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parts = urlsplit(origin)
        if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "gpu-box"}:
            raise ValueError("Use the loopback tunnel or gpu-box for the VLM judge")
        self.origin, self.confirm_external = origin.rstrip("/"), confirm_external
        self.judge_id = "http-vlm:" + VLM_MODEL
        self.client = httpx.Client(
            timeout=timeout_s, follow_redirects=False, trust_env=False, transport=transport
        )

    def choose(self, image: Path, options: dict[str, str]) -> Verdict:
        if not self.confirm_external or os.environ.get("INSTABAY_DECISIONS_ENABLED") != "1":
            raise RuntimeError("HUMAN: set INSTABAY_DECISIONS_ENABLED=1 and confirm the judge")
        try:
            response = self.client.post(
                self.origin + "/v1/vlm-choice",
                json={
                    "model": VLM_MODEL,
                    "image": base64.b64encode(image.read_bytes()).decode("ascii"),
                    "instructions": (
                        "You sort resort photographs for an Instagram content plan. Pick the "
                        "one content pillar this photo supports best, judging only what is "
                        "visible."
                    ),
                    "options": options,
                },
            )
        except httpx.HTTPError:
            raise RuntimeError("VLM judge is unreachable; is the tunnel open?") from None
        if response.status_code != 200:
            raise RuntimeError(f"VLM judge rejected the request (HTTP {response.status_code})")
        verdict = Verdict.model_validate(response.json()["verdict"])
        if verdict.choice is not None and verdict.choice not in options:
            return Verdict(choice=None, reason="Judge answered outside the requested pillars")
        return verdict

    def close(self) -> None:
        self.client.close()
