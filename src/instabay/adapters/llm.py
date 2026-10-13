"""NFR-05, NFR-06: typed, provider-independent LLM boundary."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ImageInput(BaseModel):
    """FR-04: a photo the multimodal writer sees; bytes are bound by hash in the cache key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompletionRequest(BaseModel):
    """NFR-03: exact prompt bytes, inputs and schema determine the cache key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    slot_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=512, gt=0)
    validation_feedback: str | None = None
    images: list[ImageInput] = Field(default_factory=list, max_length=6, exclude_if=lambda v: not v)


class Completion(BaseModel):
    """NFR-06: provider usage metadata; raw output is validated by the caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    output_json: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)


class LLMClient(Protocol):
    """NFR-05: fake first; real providers can implement this in a later phase."""

    def complete(self, request: CompletionRequest) -> Completion:
        """NFR-06: return JSON and measured usage, without logging credentials."""
        ...
