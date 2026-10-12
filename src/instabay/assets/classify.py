"""FR-04, FR-08: d3-flash sorts owner photos by pillar; owner corrections measure it."""

from collections import Counter
from pathlib import Path

from pydantic import Field

from instabay.assets.judge import PillarJudge
from instabay.assets.library import CONFIDENT, Asset, AssetLibrary
from instabay.core.schemas import Boundary, BrandConstitution, canonical_hash
from instabay.decisions.engine import DecisionUnavailableError, Question
from instabay.decisions.vision import VisionDecisionEngine

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
STATE = "Insta Bay brand photo library: classify one resort photograph."


def prompt(name: str) -> str:
    return (PROMPTS / f"decision_asset_{name}_en.md").read_text().strip()


def asset_questions(brand: BrandConstitution) -> dict[str, Question]:
    """FR-08: pillar choice uses the frozen brand's own descriptions as criteria."""
    return {
        "pillar": Question(
            type="choice",
            instructions=prompt("pillar"),
            criteria={p.id: p.description for p in brand.pillars},
        ),
        "people": Question(type="noul", instructions=prompt("people")),
    }


def fidelity_questions() -> dict[str, Question]:
    """Rule 6: a generated view must keep the real place and look like a photograph."""
    return {
        "same_place": Question(type="noul", instructions=prompt("fidelity")),
        "photoreal": Question(type="noul", instructions=prompt("realism")),
    }


class ClassifyReport(Boundary):
    classified: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: list[str] = Field(default_factory=list)
    judged: int = Field(default=0, ge=0)
    described: int = Field(default=0, ge=0)


def classify_assets(
    library: AssetLibrary,
    engine: VisionDecisionEngine,
    brand: BrandConstitution,
    *,
    force: bool = False,
    judge: PillarJudge | None = None,
) -> ClassifyReport:
    """FR-04: unclassified (or all, with force) photos; one failure never blocks the rest.

    Photos whose top d3 pillar is below the review threshold go to the VLM judge, if given, and
    the judge drafts EN/AR descriptions for photos the owner has not described.
    """
    questions = asset_questions(brand)
    questions_hash = canonical_hash({k: v.wire() for k, v in questions.items()})
    done, skipped, failed, judged = 0, 0, [], 0
    unsure: list[Asset] = []
    options = {p.id: p.description for p in brand.pillars}
    for asset in library.all():
        if asset.rejected or (asset.model_pillar and not force):
            skipped += 1
            continue
        try:
            answers = engine.decide(STATE, questions, [library.path(asset)])
        except (DecisionUnavailableError, ValueError):
            failed.append(asset.id)
            continue
        pillar = answers["pillar"]
        # d3's own `confidence` runs below its top-option probability; the top probability is
        # what the owner sees and what the provisional review threshold applies to.
        top = max(pillar.probabilities.values()) if pillar.probabilities else pillar.confidence
        library.record_classification(
            asset.id,
            engine_id=engine.engine_id,
            synthetic=engine.synthetic,
            questions_hash=questions_hash,
            answers={k: v.model_dump(mode="json") for k, v in answers.items()},
            pillar=None if pillar.abstained else pillar.choice,
            confidence=top,
            people=answers["people"].noul,
        )
        done += 1
        if pillar.abstained or top < CONFIDENT:
            unsure.append(asset)
    # Second pass, so the GPU swaps from d3 to the judge once rather than per photo.
    for asset in unsure if judge is not None else []:
        try:
            verdict = judge.choose(library.path(asset), options)  # type: ignore[union-attr]
        except RuntimeError as error:
            library.record_vlm(asset.id, None, str(error))
            continue
        library.record_vlm(asset.id, verdict.choice, verdict.reason)
        judged += 1
    # Third pass: draft the EN/AR visible-content lines the owner did not write.
    described = 0
    for asset in library.all() if judge is not None else []:
        if asset.rejected or asset.described or asset.note_source == "owner":
            continue
        try:
            text = judge.describe(library.path(asset))  # type: ignore[union-attr]
        except RuntimeError:
            continue
        if text.en.strip() and text.ar.strip():
            library.record_description(asset.id, text.en, text.ar)
            described += 1
    return ClassifyReport(
        classified=done, skipped=skipped, failed=failed, judged=judged, described=described
    )


class Agreement(Boundary):
    """FR-08: classifier vs owner labels; kappa is None until two labels exist."""

    labelled: int = Field(ge=0)
    agree: int = Field(ge=0)
    accuracy: float | None = None
    kappa: float | None = None


def agreement(assets: list[Asset], source: str = "d3") -> Agreement:
    """FR-08: Cohen's kappa of d3 (or the VLM judge) against the owner's pillar labels."""
    pairs = [
        (a.owner_pillar, a.model_pillar if source == "d3" else a.vlm_pillar)
        for a in assets
        if a.owner_pillar and (a.model_pillar if source == "d3" else a.vlm_pillar)
    ]
    if not pairs:
        return Agreement(labelled=0, agree=0)
    n = len(pairs)
    agree = sum(o == m for o, m in pairs)
    observed = agree / n
    owner, model = Counter(o for o, _ in pairs), Counter(m for _, m in pairs)
    expected = sum(owner[k] * model[k] for k in owner) / (n * n)
    kappa = None if expected >= 1 else (observed - expected) / (1 - expected)
    return Agreement(labelled=n, agree=agree, accuracy=observed, kappa=kappa)
