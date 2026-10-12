"""NFR-03, NFR-06, NFR-07: validation, budgets, privacy and cache correctness."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from instabay.adapters.fake_llm import FakeLLM, FakeLLMMissingFixture
from instabay.adapters.llm import Completion, CompletionRequest
from instabay.core.fixture_schemas import BriefFixture, CopyFixture, JudgeFixture
from instabay.db import SQLiteCallStore
from instabay.llm import LLMBudgetExceeded, LLMOutputError, LLMProviderError, LLMService, RunBudget

FIXTURES = Path("tests/fixtures/llm")


class SequenceLLM:
    """NFR-07: deterministic provider failure and usage injection."""

    def __init__(self, outputs: list[str], *, cost: float = 0) -> None:
        self.outputs = iter(outputs)
        self.requests: list[CompletionRequest] = []
        self.cost = cost

    def complete(self, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        return Completion(
            model=request.model,
            output_json=next(self.outputs),
            input_tokens=10,
            output_tokens=10,
            cost_usd=self.cost,
        )


def generate(service: LLMService, **inputs: str) -> CopyFixture:
    return service.generate(
        template_name="copy_en", slot_id="wk42-tue-1", inputs=inputs, output_type=CopyFixture
    )


@pytest.mark.parametrize(
    ("template", "schema"),
    [
        ("brief_writer", BriefFixture),
        ("copy_en", CopyFixture),
        ("copy_ar", CopyFixture),
        ("judge", JudgeFixture),
    ],
)
def test_worked_example_fixtures_validate(
    tmp_path: Path, template: str, schema: type[BaseModel]
) -> None:
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        result = LLMService(FakeLLM(FIXTURES), store).generate(
            template_name=template, slot_id="wk42-tue-1", inputs={}, output_type=schema
        )
        assert isinstance(result, schema)
        record = store.calls()[0]
        assert record.status == "success"
        assert record.created_at.utcoffset().total_seconds() == 0
        assert record.cost_usd == 0
        assert record.input_tokens > 0
        assert (
            record.prompt_hash
            == hashlib.sha256(
                (Path("src/instabay/prompts") / f"{template}.md").read_bytes()
            ).hexdigest()
        )


def test_cache_survives_service_and_database_restart(tmp_path: Path) -> None:
    fake = FakeLLM(FIXTURES)
    db = tmp_path / "db.sqlite"
    with SQLiteCallStore(db) as store:
        original = generate(LLMService(fake, store), angle="quiet")
    with SQLiteCallStore(db) as store:
        service = LLMService(fake, store, budget=RunBudget(max_calls=0))
        assert generate(service, angle="quiet") == original
        assert fake.calls == 1
        assert service.usage.calls == 0
        assert [row.status for row in store.calls()] == ["success", "cached"]
        assert store.calls()[1].input_tokens == 0


def test_prompt_and_inputs_invalidate_cache(tmp_path: Path) -> None:
    fake = FakeLLM(FIXTURES)
    prompt = tmp_path / "copy_en.md"
    prompt.write_text("Prompt version one\n")
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        service = LLMService(fake, store, prompt_dir=tmp_path)
        generate(service, angle="quiet")
        generate(service, angle="energetic")
        prompt.write_text("Prompt version two\n")
        generate(service, angle="quiet")
        assert fake.calls == 3
        assert len({row.cache_key for row in store.calls()}) == 3
        assert len({row.prompt_hash for row in store.calls()}) == 2


@pytest.mark.parametrize(
    "change", ["model", "schema", "temperature", "max_output_tokens", "slot_id"]
)
def test_generation_parameters_are_part_of_cache_identity(tmp_path: Path, change: str) -> None:
    class AnotherCopy(CopyFixture):
        pass

    provider = SequenceLLM([json.dumps({"caption": "quiet", "alt_text": "water"})] * 2)
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        service = LLMService(provider, store)
        generate(service)
        service.generate(
            template_name="copy_en",
            slot_id="another-slot" if change == "slot_id" else "wk42-tue-1",
            inputs={},
            output_type=AnotherCopy if change == "schema" else CopyFixture,
            model="other-model" if change == "model" else "fake-fixture-v1",
            temperature=0.5 if change == "temperature" else 0,
            max_output_tokens=256 if change == "max_output_tokens" else 512,
        )
        assert len(provider.requests) == 2


def test_one_retry_receives_safe_feedback_and_counts_both_attempts(tmp_path: Path) -> None:
    private_marker = "private-input-must-not-appear"
    fake = SequenceLLM(
        [
            json.dumps({"caption": {"bad": private_marker}}),
            '{"caption":"quiet","alt_text":"water"}',
        ],
        cost=0.01,
    )
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        service = LLMService(fake, store)
        assert generate(service).caption == "quiet"
        assert len(fake.requests) == 2
        assert fake.requests[1].validation_feedback
        assert private_marker not in fake.requests[1].validation_feedback
        assert private_marker not in str([row.model_dump() for row in store.calls()])
        assert [row.status for row in store.calls()] == ["invalid_output", "success"]
        assert service.usage.tokens == 40
        assert service.usage.cost_usd == pytest.approx(0.02)


def test_invalid_output_fails_after_two_attempts_and_never_caches(tmp_path: Path) -> None:
    fake = SequenceLLM(["not JSON", "{}"])
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(LLMOutputError):
            generate(LLMService(fake, store))
        assert len(fake.requests) == 2
        for row in store.calls():
            assert row.status == "invalid_output"
            assert store.get_cached(row.cache_key) is None


def test_corrupt_cache_is_evicted(tmp_path: Path) -> None:
    fake = FakeLLM(FIXTURES)
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        service = LLMService(fake, store)
        generate(service)
        store.put_cached(store.calls()[0].cache_key, "broken JSON")
        generate(service)
        assert fake.calls == 2
        assert store.calls()[-1].status == "success"


def test_unknown_fixture_fails_and_logs_metadata(tmp_path: Path) -> None:
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(FakeLLMMissingFixture):
            LLMService(FakeLLM(FIXTURES), store).generate(
                template_name="copy_en", slot_id="unknown", inputs={}, output_type=CopyFixture
            )
        assert store.calls()[0].status == "provider_error"
        assert store.calls()[0].error_type == "provider_failure"


def test_mislabelled_fixture_fails(tmp_path: Path) -> None:
    fixture = json.loads((FIXTURES / "copy_en__wk42-tue-1.json").read_text())
    fixture["slot_id"] = "wrong-slot"
    (tmp_path / "copy_en__wk42-tue-1.json").write_text(json.dumps(fixture))
    with SQLiteCallStore(tmp_path / "db.sqlite") as store, pytest.raises(FakeLLMMissingFixture):
        generate(LLMService(FakeLLM(tmp_path), store))


@pytest.mark.parametrize("template", ["../copy_en", "/tmp/file", "copy_en.md"])
def test_prompt_names_cannot_escape_prompt_directory(tmp_path: Path, template: str) -> None:
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(ValueError, match="Invalid prompt"):
            LLMService(FakeLLM(FIXTURES), store).generate(
                template_name=template, slot_id="wk42-tue-1", inputs={}, output_type=CopyFixture
            )
        assert store.calls() == []


def test_inputs_are_not_written_to_call_log(tmp_path: Path) -> None:
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        generate(LLMService(FakeLLM(FIXTURES), store), context="private-input-must-not-appear")
        assert "private-input-must-not-appear" not in store.calls()[0].model_dump_json()


def test_provider_errors_do_not_expose_private_exception_text(tmp_path: Path) -> None:
    class FailingProvider:
        def complete(self, request: CompletionRequest) -> Completion:
            raise RuntimeError("private-provider-credential-must-not-appear")

    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(LLMProviderError) as failure:
            generate(LLMService(FailingProvider(), store))
        assert "private-provider-credential" not in str(failure.value)
        assert failure.value.__suppress_context__
        assert "private-provider-credential" not in store.calls()[0].model_dump_json()
        assert store.calls()[0].status == "provider_error"


def test_call_budget_stops_retry(tmp_path: Path) -> None:
    fake = SequenceLLM(["{}", "{}"])
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(LLMBudgetExceeded):
            generate(LLMService(fake, store, budget=RunBudget(max_calls=1)))
        assert len(fake.requests) == 1


@pytest.mark.parametrize("budget", [RunBudget(max_tokens=19), RunBudget(max_cost_usd=0.009)])
def test_actual_usage_over_cap_is_logged_and_not_cached(tmp_path: Path, budget: RunBudget) -> None:
    fake = SequenceLLM(['{"caption":"quiet","alt_text":"water"}'], cost=0.01)
    with SQLiteCallStore(tmp_path / "db.sqlite") as store:
        service = LLMService(fake, store, budget=budget)
        with pytest.raises(LLMBudgetExceeded):
            generate(service)
        assert len(fake.requests) == 1
        assert store.calls()[0].cost_usd == 0.01
        assert store.get_cached(store.calls()[0].cache_key) is None
        with pytest.raises(LLMBudgetExceeded):
            generate(service)
        assert len(fake.requests) == 1
