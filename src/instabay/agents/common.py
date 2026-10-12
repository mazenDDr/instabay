"""FR-04, NFR-03: typed agent inputs and exact prompt provenance."""

import hashlib

from pydantic import BaseModel, JsonValue, TypeAdapter

from instabay.llm import LLMService


def agent_inputs(**values: BaseModel | str | int | list[str]) -> dict[str, JsonValue]:
    """NFR-03: convert structured domain inputs to the provider's JSON boundary."""
    payload = {
        key: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        for key, value in values.items()
    }
    return TypeAdapter(dict[str, JsonValue]).validate_python(payload)


def prompt_hashes(service: LLMService, names: list[str]) -> dict[str, str]:
    """NFR-03: preserve the exact templates used to produce approved content."""
    return {
        name: hashlib.sha256((service.prompt_dir / f"{name}.md").read_bytes()).hexdigest()
        for name in names
    }
