"""FR-04, FR-08: real parallel requests, shared budgets and one refinement only."""

import json
from pathlib import Path
from threading import Barrier, Lock

import pytest

from instabay.adapters.fake_llm import FakeLLM
from instabay.adapters.llm import Completion, CompletionRequest
from instabay.agents.judge import Judge, write_bilingual
from instabay.core.schemas import Copy, Post
from instabay.db import SQLiteCallStore
from instabay.llm import LLMBudgetExceeded, LLMService, RunBudget
from instabay.repository import Repository
from tests.support import demo_brand, draft_post


class ParallelFake(FakeLLM):
    def __init__(self) -> None:
        super().__init__(Path("tests/fixtures/llm"))
        self.barrier = Barrier(2)
        self.requests: list[CompletionRequest] = []
        self.requests_lock = Lock()

    def complete(self, request: CompletionRequest) -> Completion:
        with self.requests_lock:
            self.requests.append(request)
        self.barrier.wait(timeout=5)
        return super().complete(request)


def test_writers_overlap_and_ar_never_receives_english_caption(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "domain.sqlite")
    post = draft_post(repository)
    slot = repository.slots("2026-w42")[0]
    fake = ParallelFake()
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        service = LLMService(fake, store)
        en, ar = write_bilingual(service, slot, demo_brand(), post.brief)
        assert en.caption.startswith("3 ways")
        assert "ثلاث" in ar.caption
        assert fake.calls == 2
        assert service.usage.calls == 2
        assert service.usage.tokens == 535
        assert len(store.calls()) == 2
        assert fake.requests[0].inputs["brief"] == fake.requests[1].inputs["brief"]
        assert all(
            "en" not in request.inputs and "ar" not in request.inputs for request in fake.requests
        )


def test_parallel_writers_share_the_call_cap(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "domain.sqlite")
    post = draft_post(repository)
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        fake = FakeLLM(Path("tests/fixtures/llm"))
        service = LLMService(fake, store, budget=RunBudget(max_calls=1))
        with pytest.raises(LLMBudgetExceeded):
            write_bilingual(service, repository.slots("2026-w42")[0], demo_brand(), post.brief)
        assert fake.calls == 1


def test_bad_rules_trigger_one_revision_then_flag_remaining_failure(tmp_path: Path) -> None:
    class BadCaptionFake(FakeLLM):
        def complete(self, request: CompletionRequest) -> Completion:
            result = super().complete(request)
            if request.template_name in {"copy_en", "copy_en_revision"}:
                return result.model_copy(
                    update={
                        "output_json": json.dumps(
                            {"caption": "Enjoy our infinity pool", "alt_text": "A private pool"}
                        )
                    }
                )
            return result

    repository = Repository(tmp_path / "domain.sqlite")
    original = draft_post(repository)
    post = Post.model_validate(
        {
            **original.model_dump(),
            "en": Copy(caption="Our infinity pool", alt_text="An invented pool"),
        }
    )
    with SQLiteCallStore(tmp_path / "calls.sqlite") as store:
        service = LLMService(BadCaptionFake(Path("tests/fixtures/llm")), store)
        revised, review = Judge(service).check_and_refine(
            post, repository.slots("2026-w42")[0], demo_brand()
        )
        assert revised.revision == 1
        assert review.flagged
        assert not review.rules.passed
        assert len([row for row in store.calls() if row.template_name.endswith("revision")]) == 2
        before = service.usage.calls
        again, _ = Judge(service).check_and_refine(
            revised, repository.slots("2026-w42")[0], demo_brand()
        )
        assert again.revision == 1
        assert service.usage.calls == before
