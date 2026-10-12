"""NFR-03, NFR-06, NFR-07: schema-first LLM calls, hashed prompts and local cache."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from instabay.adapters.call_store import CallRecord, CallStore
from instabay.adapters.fake_llm import FakeLLMMissingFixture
from instabay.adapters.llm import Completion, CompletionRequest, LLMClient


class LLMOutputError(ValueError):
    """NFR-03: both attempts failed schema validation; nothing enters the cache."""


class LLMProviderError(RuntimeError):
    """NFR-04: provider failures are surfaced without raw exception text or credentials."""


class LLMBudgetExceeded(RuntimeError):
    """NFR-06: stop a run when its configured paid-call budget is exhausted."""


class RunBudget(BaseModel):
    """NFR-06: per-run caps; actual usage includes failed validation attempts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: int = Field(default=100, ge=0)
    max_tokens: int = Field(default=20_000, ge=0)
    max_cost_usd: float = Field(default=1, ge=0, allow_inf_nan=False)


class RunUsage(BaseModel):
    """NFR-06: measured run usage, independent of persisted historical totals."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0, allow_inf_nan=False)


class LLMService:
    """NFR-03, NFR-06: provider-agnostic validation and sanitized call logging."""

    def __init__(
        self,
        client: LLMClient,
        store: CallStore,
        prompt_dir: Path | None = None,
        budget: RunBudget | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.prompt_dir = prompt_dir or Path(__file__).parent / "prompts"
        self.budget = budget or RunBudget()
        self.usage = RunUsage()

    def generate[Output: BaseModel](
        self,
        *,
        template_name: str,
        slot_id: str,
        inputs: dict[str, JsonValue],
        output_type: type[Output],
        model: str = "fake-fixture-v1",
        temperature: float = 0,
        max_output_tokens: int = 512,
    ) -> Output:
        """NFR-03: validate JSON, retry once, cache by all generation-affecting inputs."""
        if not re.fullmatch(r"[a-z][a-z0-9_]*", template_name):
            raise ValueError("Invalid prompt template name")
        prompt_bytes = (self.prompt_dir / f"{template_name}.md").read_bytes()
        request = CompletionRequest(
            template_name=template_name,
            slot_id=slot_id,
            model=model,
            prompt=prompt_bytes.decode("utf-8"),
            prompt_hash=hashlib.sha256(prompt_bytes).hexdigest(),
            inputs=inputs,
            output_schema=TypeAdapter(dict[str, JsonValue]).validate_python(
                output_type.model_json_schema()
            ),
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        cache_key = hashlib.sha256(
            json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        cached = self.store.get_cached(cache_key)
        if cached is not None:
            try:
                result = output_type.model_validate_json(cached)
            except ValidationError:
                self.store.delete_cached(cache_key)
            else:
                self._log(request, cache_key, "cached", attempt=0, latency_ms=0)
                return result

        for attempt in (1, 2):
            self._check_budget(before_call=True)
            started = perf_counter()
            self.usage.calls += 1
            try:
                completion = self.client.complete(request)
            except Exception as error:
                self._log(
                    request,
                    cache_key,
                    "provider_error",
                    attempt=attempt,
                    latency_ms=(perf_counter() - started) * 1000,
                    error_type="provider_failure",
                )
                if isinstance(error, FakeLLMMissingFixture):
                    raise
                raise LLMProviderError(
                    "LLM provider failed; inspect sanitized call records"
                ) from None
            elapsed_ms = (perf_counter() - started) * 1000
            self.usage.tokens += completion.input_tokens + completion.output_tokens
            self.usage.cost_usd += completion.cost_usd
            try:
                result = output_type.model_validate_json(completion.output_json)
            except ValidationError as error:
                self._log(
                    request,
                    cache_key,
                    "invalid_output",
                    attempt=attempt,
                    latency_ms=elapsed_ms,
                    completion=completion,
                    error_type="schema_validation",
                )
                self._check_budget(before_call=False)
                # Validation errors may contain inputs or tokens. Send only paths and error codes.
                feedback = json.dumps(
                    [{"loc": item["loc"], "type": item["type"]} for item in error.errors()]
                )
                request = request.model_copy(update={"validation_feedback": feedback})
            else:
                self._log(
                    request,
                    cache_key,
                    "success",
                    attempt=attempt,
                    latency_ms=elapsed_ms,
                    completion=completion,
                )
                self._check_budget(before_call=False)
                self.store.put_cached(cache_key, result.model_dump_json())
                return result
        raise LLMOutputError("LLM output failed schema validation on both attempts")

    def _check_budget(self, *, before_call: bool) -> None:
        calls_exceeded = (
            self.usage.calls >= self.budget.max_calls
            if before_call
            else self.usage.calls > self.budget.max_calls
        )
        tokens_exceeded = (
            self.usage.tokens >= self.budget.max_tokens
            if before_call
            else self.usage.tokens > self.budget.max_tokens
        )
        cost_exceeded = (
            self.usage.cost_usd >= self.budget.max_cost_usd
            if before_call
            else self.usage.cost_usd > self.budget.max_cost_usd
        )
        if calls_exceeded or tokens_exceeded or cost_exceeded:
            raise LLMBudgetExceeded("Run budget exhausted; inspect call records and run usage")

    def _log(
        self,
        request: CompletionRequest,
        cache_key: str,
        status: Literal["success", "invalid_output", "provider_error", "cached"],
        *,
        attempt: int,
        latency_ms: float,
        completion: Completion | None = None,
        error_type: Literal["schema_validation", "provider_failure"] | None = None,
    ) -> None:
        self.store.log_call(
            CallRecord(
                id=str(uuid4()),
                created_at=datetime.now(UTC),
                template_name=request.template_name,
                slot_id=request.slot_id,
                model=completion.model if completion else request.model,
                prompt_hash=request.prompt_hash,
                cache_key=cache_key,
                status=status,
                attempt=attempt,
                latency_ms=latency_ms,
                input_tokens=completion.input_tokens if completion else 0,
                output_tokens=completion.output_tokens if completion else 0,
                cost_usd=completion.cost_usd if completion else 0,
                error_type=error_type,
            )
        )
