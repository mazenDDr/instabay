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


class FixtureGroup(BaseModel):
    """NFR-07: compact canned variants; selection never generates or rewrites text."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    selectors: list[str]
    cases: dict[str, dict[str, JsonValue]]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class FixtureCatalog(BaseModel):
    """NFR-07: explicit template+slot whitelist points to prerecorded response groups."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    entries: dict[str, str]
    groups: dict[str, FixtureGroup]

    def response(self, template: str, slot_id: str, arm: dict[str, JsonValue]) -> Fixture:
        """NFR-07: unknown slots, templates and arms raise; there is no generic fallback."""
        group_name = self.entries.get(f"{template}__{slot_id}")
        if group_name is None or group_name not in self.groups:
            raise FakeLLMMissingFixture("No catalog fixture for this template and slot")
        group = self.groups[group_name]
        key = "|".join(str(arm.get(name, "")) for name in group.selectors)
        if key not in group.cases:
            raise FakeLLMMissingFixture("No recorded variant for this arm")
        return Fixture(
            template_name=template,
            slot_id=slot_id,
            response=group.cases[key],
            input_tokens=group.input_tokens,
            output_tokens=group.output_tokens,
        )


class FakeLLM:
    """NFR-07: replay local JSON fixtures; usage is illustrative, never paid spend."""

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir
        self.calls = 0
        self._lock = Lock()
        catalog = fixture_dir / "cycle-catalog.json"
        self.catalog = (
            FixtureCatalog.model_validate_json(catalog.read_bytes()) if catalog.exists() else None
        )

    def complete(self, request: CompletionRequest) -> Completion:
        """NFR-07: select strictly by template name plus slot ID."""
        path = self.fixture_dir / f"{request.template_name}__{request.slot_id}.json"
        if path.is_file():
            fixture = Fixture.model_validate_json(path.read_bytes())
        elif self.catalog is not None:
            slot = request.inputs.get("slot", {})
            arm = slot.get("arm", {}) if isinstance(slot, dict) else {}
            fixture = self.catalog.response(
                request.template_name, request.slot_id, arm if isinstance(arm, dict) else {}
            )
        else:
            raise FakeLLMMissingFixture("No fixture for this template and slot")
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
