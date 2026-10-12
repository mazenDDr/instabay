"""NFR-03, NFR-06: cache and call-ledger persistence boundary."""

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class CallRecord(BaseModel):
    """NFR-06: metadata only; never store prompts, inputs or provider error text here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    created_at: AwareDatetime
    template_name: str
    slot_id: str
    model: str
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["success", "invalid_output", "provider_error", "cached"]
    attempt: int = Field(ge=0, le=2)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    error_type: Literal["schema_validation", "provider_failure"] | None = None
    run_id: str | None = None

    @field_validator("created_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        """NFR-06: normalize aware timestamps to UTC at the database boundary."""
        return value.astimezone(UTC)


class CallStore(Protocol):
    """NFR-05: isolate persistence from LLM orchestration."""

    def get_cached(self, cache_key: str) -> str | None:
        """NFR-03: retrieve a validated JSON response by content identity."""
        ...

    def put_cached(self, cache_key: str, output_json: str) -> None:
        """NFR-03: cache schema-valid responses only."""
        ...

    def delete_cached(self, cache_key: str) -> None:
        """NFR-03: remove an entry that no longer validates."""
        ...

    def log_call(self, record: CallRecord) -> None:
        """NFR-06: append sanitized usage metadata."""
        ...
