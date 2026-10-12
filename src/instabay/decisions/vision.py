"""FR-08, NFR-04: image-conditioned System One decisions (d3-flash); offline fakes first."""

import base64
import hashlib
import os
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import Field, JsonValue

from instabay.core.schemas import Boundary, Hash, canonical_hash
from instabay.decisions.engine import (
    Answer,
    DecisionUnavailableError,
    Question,
    normalize_answers,
)
from instabay.decisions.jev_http import SystemOneConfig

D3_FLASH = "vllm-sr/d3-flash"
MAX_IMAGE_BYTES = 25_000_000


def image_digest(path: Path) -> str:
    """NFR-03: decisions bind exact image bytes, not file names."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VisionDecisionEngine(Protocol):
    """NFR-05: every image classifier/fidelity checker answers the same typed questions."""

    engine_id: str
    synthetic: bool

    def decide(
        self,
        state: str | dict[str, JsonValue],
        questions: dict[str, Question],
        images: list[Path],
    ) -> dict[str, Answer]: ...


class VisionFixture(Boundary):
    """NFR-07: exact state, questions and image bytes; explicitly synthetic."""

    state_hash: Hash
    questions_hash: Hash
    images_sha256: list[Hash] = Field(min_length=1)
    response: dict[str, JsonValue]


def vision_key(
    state: str | dict[str, JsonValue], questions: dict[str, Question], images: list[Path]
) -> tuple[str, str, list[str]]:
    """NFR-07: one identity shared by fixture writers and the fake engine."""
    return (
        canonical_hash({"state": state}),
        canonical_hash({k: v.wire() for k, v in questions.items()}),
        [image_digest(p) for p in images],
    )


class FakeVisionEngine:
    """NFR-07: fixture-first; unknown images fail rather than guessing a pillar."""

    engine_id = "fake-d3-flash-v1"
    synthetic = True

    def __init__(self, fixtures: list[VisionFixture]) -> None:
        self.fixtures = fixtures
        self.calls = 0

    @classmethod
    def from_dir(cls, path: Path) -> "FakeVisionEngine":
        return cls(
            [VisionFixture.model_validate_json(p.read_bytes()) for p in sorted(path.glob("*.json"))]
        )

    def decide(
        self,
        state: str | dict[str, JsonValue],
        questions: dict[str, Question],
        images: list[Path],
    ) -> dict[str, Answer]:
        self.calls += 1
        state_hash, questions_hash, shas = vision_key(state, questions, images)
        for fixture in self.fixtures:
            if (fixture.state_hash, fixture.questions_hash, fixture.images_sha256) == (
                state_hash,
                questions_hash,
                shas,
            ):
                return normalize_answers(fixture.response, questions)
        raise DecisionUnavailableError("No exact synthetic vision fixture")


class D3FlashHTTPEngine:
    """FR-08: HUMAN-enabled client for gpu_worker/vision_server.py over the Tailscale tunnel."""

    synthetic = False

    def __init__(
        self,
        config: SystemOneConfig,
        *,
        confirm_external: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if config.model != D3_FLASH:
            raise ValueError("The vision engine serves only the pinned d3-flash model")
        self.config, self.confirm_external = config, confirm_external
        self.engine_id = "http-d3-flash:" + canonical_hash(config)
        self.client = httpx.Client(
            timeout=config.timeout_s, follow_redirects=False, trust_env=False, transport=transport
        )

    def decide(
        self,
        state: str | dict[str, JsonValue],
        questions: dict[str, Question],
        images: list[Path],
    ) -> dict[str, Answer]:
        if not self.confirm_external or os.environ.get("INSTABAY_DECISIONS_ENABLED") != "1":
            raise DecisionUnavailableError("HUMAN: explicitly enable external decision requests")
        if not images or any(p.stat().st_size > MAX_IMAGE_BYTES for p in images):
            raise DecisionUnavailableError("Vision decisions need 1+ images under 25 MB each")
        if len(str(state)) > self.config.max_state_chars:
            raise DecisionUnavailableError("Decision state exceeds configured input limit")
        payload = {
            "state": state,
            "questions": {k: v.wire() for k, v in questions.items()},
            "model": self.config.model,
            "revision": self.config.revision,
            "images": [base64.b64encode(p.read_bytes()).decode("ascii") for p in images],
        }
        try:
            response = self.client.post(
                self.config.base_url.rstrip("/") + "/v1/systemone", json=payload
            )
            if response.status_code != 200:
                raise DecisionUnavailableError(
                    f"d3-flash request rejected (HTTP {response.status_code})"
                )
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise DecisionUnavailableError("d3-flash HTTP/JSON failure") from None
        return normalize_answers(body, questions)

    def close(self) -> None:
        self.client.close()
