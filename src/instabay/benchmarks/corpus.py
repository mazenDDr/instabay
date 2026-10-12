"""FR-14: immutable 21-post corpus definition and a content-only cold replay."""

from collections import defaultdict
from pathlib import Path
from time import perf_counter
from typing import Self

from pydantic import Field, TypeAdapter, model_validator

from instabay.adapters.fake_llm import FakeLLM
from instabay.adapters.fixture_fidelity import content_signature
from instabay.agents.brand_architect import BrandArchitect
from instabay.agents.brief_writer import BriefWriter
from instabay.agents.common import agent_inputs, prompt_hashes
from instabay.agents.judge import Judge, write_bilingual
from instabay.benchmarks.models import ArabicScores, ContentEvidence
from instabay.core.hashtags import select_hashtags
from instabay.core.schemas import (
    Boundary,
    BrandConstitution,
    BrandInput,
    Copy,
    Hash,
    Identifier,
    Post,
    Slot,
    canonical_hash,
)
from instabay.db import SQLiteCallStore
from instabay.llm import LLMService, RunBudget, RunUsage


class CorpusCase(Boundary):
    """FR-14: frozen slot plus brief/copy signature prevents unnoticed corpus drift."""

    slot: Slot
    content_signature: Hash


class NegativeControl(Boundary):
    """FR-14: generic any-hotel copy with no specific brand/pillar claims."""

    id: Identifier
    en: Copy
    ar: Copy


class Corpus(Boundary):
    """FR-14: fixed 3-week/21-post quality corpus, independent of policy outcomes."""

    version: str
    brand_hash: Hash
    cases: list[CorpusCase] = Field(min_length=21, max_length=21)

    @model_validator(mode="after")
    def fixed_coverage(self) -> Self:
        if len({case.slot.id for case in self.cases}) != 21:
            raise ValueError("Corpus slot IDs must be unique")
        groups: dict[str, int] = defaultdict(int)
        for case in self.cases:
            if case.slot.brand_hash != self.brand_hash:
                raise ValueError("Every corpus slot must bind to the frozen brand")
            groups[case.slot.run_id] += 1
        if len(groups) != 3 or any(count != 7 for count in groups.values()):
            raise ValueError("Corpus must have exactly three seven-post weeks")
        return self


def replay_corpus(
    corpus: Corpus,
    inputs: BrandInput,
    store: SQLiteCallStore,
    fixture_dir: Path,
    benchmark_fixtures: Path,
) -> tuple[BrandConstitution, list[ContentEvidence], list[float]]:
    """FR-14: generate/check drafts only; no repository, approval, resume or publisher calls."""
    service = LLMService(FakeLLM(fixture_dir), store)
    evaluator = LLMService(
        FakeLLM(benchmark_fixtures), store, budget=RunBudget(max_calls=150, max_tokens=40000)
    )
    content = []
    weeks: dict[str, list[CorpusCase]] = defaultdict(list)
    for case in corpus.cases:
        weeks[case.slot.run_id].append(case)
    brand: BrandConstitution | None = None
    for run_id, cases in weeks.items():
        service.run_id, service.usage = run_id, RunUsage()
        brand = BrandArchitect(service).draft(inputs)
        if canonical_hash(brand) != corpus.brand_hash:
            raise ValueError("Brand fixture no longer matches the frozen corpus")
        for case in cases:
            slot = case.slot
            started = perf_counter()
            brief = BriefWriter(service).write(slot, brand)
            en, ar = write_bilingual(service, slot, brand, brief)
            post = Post(
                id=slot.id,
                slot_id=slot.id,
                brand_hash=slot.brand_hash,
                format=slot.arm.format,
                brief=brief,
                en=en,
                ar=ar,
                hashtags=select_hashtags(brand),
                prompt_hashes=prompt_hashes(
                    service, ["brand_architect", "brief_writer", "copy_en", "copy_ar", "judge"]
                ),
                media_path=brief.photo_uri if slot.arm.format != "reel" else None,
                media_status="concept_only" if slot.arm.format == "reel" else "reference",
            )
            post, review = Judge(service).check_and_refine(post, slot, brand)
            elapsed = (perf_counter() - started) * 1000
            if content_signature(post) != case.content_signature:
                raise ValueError("Generated content no longer matches the frozen benchmark corpus")
            calls = [
                row for row in store.calls() if row.slot_id == slot.id and row.run_id == run_id
            ]
            evaluator.run_id = "benchmark-arabic-evaluation"
            arabic = [
                evaluator.generate(
                    template_name="arabic_judge",
                    slot_id=post.id,
                    inputs=agent_inputs(post=post, brand=brand, sample=index),
                    output_type=ArabicScores,
                    model="fake-arabic-judge-fixture-v1",
                    temperature=0,
                )
                for index in range(3)
            ]
            content.append(
                ContentEvidence(
                    slot=slot,
                    post=post,
                    review=review,
                    calls=calls,
                    wall_latency_ms=elapsed,
                    arabic_samples=arabic,
                )
            )
    if brand is None:
        raise ValueError("Empty corpus")
    negative_scores = []
    evaluator.run_id = "benchmark-negative-controls"
    controls = TypeAdapter(list[NegativeControl]).validate_json(
        (benchmark_fixtures.parent / "negative_controls.json").read_bytes()
    )
    if len(controls) != 10 or len({control.id for control in controls}) != 10:
        raise ValueError("Benchmark needs ten distinct negative controls")
    for control, row in zip(controls, content[:10], strict=True):
        post = Post.model_validate(
            {
                **row.post.model_dump(),
                "id": control.id,
                "slot_id": control.id,
                "en": control.en,
                "ar": control.ar,
            }
        )
        negative_scores.append(Judge(evaluator).evaluate(post, brand).average)
    return brand, content, negative_scores
