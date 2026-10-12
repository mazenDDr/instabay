"""NFR-07: canned responses only; unknown template/slot pairs fail loudly."""

import json
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from instabay.adapters.llm import Completion, CompletionRequest


class FakeLLMMissingFixture(LookupError):
    """NFR-07: there is no implicit response or live-provider fallback."""


class Fixture(BaseModel):
    """NFR-07: validate recorded fixture envelopes before replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template_name: str
    slot_id: str
    response: dict[str, JsonValue]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class FakeLLM:
    """NFR-07: replay local JSON fixtures; usage is illustrative, never paid spend."""

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir
        self.calls = 0
        self._lock = Lock()

    def complete(self, request: CompletionRequest) -> Completion:
        """NFR-07: select strictly by template name plus slot ID."""
        path = self.fixture_dir / f"{request.template_name}__{request.slot_id}.json"
        if not path.is_file():
            raise FakeLLMMissingFixture("No fixture for this template and slot")
        fixture = Fixture.model_validate_json(path.read_bytes())
        if (fixture.template_name, fixture.slot_id) != (request.template_name, request.slot_id):
            raise FakeLLMMissingFixture("Fixture identity does not match the requested key")
        with self._lock:
            self.calls += 1
        return Completion(
            model="fake-fixture-v1",
            output_json=json.dumps(fixture.response, ensure_ascii=False),
            input_tokens=fixture.input_tokens,
            output_tokens=fixture.output_tokens,
            cost_usd=0,
        )
