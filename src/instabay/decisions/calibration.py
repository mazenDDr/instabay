"""FR-08: grouped validation-only confidence fitting; held-out evidence controls abstention."""

import math
from collections import defaultdict
from typing import Literal, Self

from pydantic import Field, model_validator

from instabay.core.schemas import Boundary, Hash, canonical_hash
from instabay.decisions.engine import Answer, Language


class CalibrationCase(Boundary):
    """FR-08: prediction and independent gold label tied to exact state and question hashes."""

    item_id: str
    group_id: str
    language: Language
    state_hash: Hash
    question_id: str
    question_hash: Hash
    answer: Answer
    gold: str | float | bool
    human_gold: str | float | bool | None = None
    human_actor: str | None = None

    @property
    def correct(self) -> bool:
        expected = self.human_gold if self.human_gold is not None else self.gold
        actual = self.answer.label
        if isinstance(actual, bool):
            return isinstance(expected, bool) and actual == expected
        if isinstance(actual, str):
            return isinstance(expected, str) and actual == expected
        return not isinstance(expected, (bool, str)) and abs(actual - expected) <= 0.25

    @model_validator(mode="after")
    def audit_provenance(self) -> Self:
        if (self.human_gold is None) != (self.human_actor is None):
            raise ValueError("Human audit label and actor must be provided together")
        if self.human_actor is not None and not self.human_actor.strip():
            raise ValueError("Human actor cannot be blank")
        return self


class CalibrationData(Boundary):
    """FR-08: real gold requires 300 unique bilingual items and 60 human-audited items."""

    engine_id: str
    brand_hash: Hash
    provenance: Literal["human_audited", "synthetic"]
    cases: list[CalibrationCase] = Field(min_length=1)
    seed: int = 7

    @model_validator(mode="after")
    def no_duplicate_leakage(self) -> Self:
        keys = set()
        states: dict[str, str] = {}
        items: dict[str, tuple[str, Language, str]] = {}
        for c in self.cases:
            key = (c.item_id, c.question_id)
            if key in keys:
                raise ValueError("Duplicate item/question pair")
            keys.add(key)
            scope = (c.group_id, c.language, c.state_hash)
            if c.item_id in items and items[c.item_id] != scope:
                raise ValueError("Conflicting item identity")
            items[c.item_id] = scope
            if c.state_hash in states and states[c.state_hash] != c.group_id:
                raise ValueError("Repeated content must stay in one split group")
            states[c.state_hash] = c.group_id
        if self.provenance == "human_audited":
            audited = {c.item_id for c in self.cases if c.human_gold is not None}
            if (
                len(items) < 300
                or sum(v[1] == "ar" for v in items.values()) / len(items) < 0.4
                or len(audited) < 60
            ):
                raise ValueError(
                    "Real calibration requires 300 items, >=40% Arabic and 60 audited items"
                )
        return self


class Cell(Boundary):
    """FR-08: fitted temperature/threshold plus separate untouched test metrics per language."""

    question_hash: Hash
    temperature: float = Field(gt=0)
    threshold: float | None = Field(default=None, ge=0, le=1)
    validation_n: int
    test_n: int
    accepted_test_n: int
    precision: float | None
    precision_ci95: tuple[float, float] | None
    accuracy: float | None
    ece_before: float | None
    ece_after: float | None
    escalation_rate: float
    enabled: bool = False


class CalibrationProfile(Boundary):
    """FR-08: domain/engine/question scoped, content-addressed evidence, no default thresholds."""

    engine_id: str
    brand_hash: Hash
    provenance: Literal["human_audited", "synthetic"]
    dataset_hash: Hash
    split_items: dict[str, list[str]]
    cells: dict[str, Cell]
    target_precision: float = 0.95
    max_escalation: float = 0.7
    audit_agreement: float | None = None
    audit_kappa: dict[str, float | None] = Field(default_factory=dict)
    status: Literal["enabled", "d1_only", "disabled"] = "disabled"

    @property
    def hash(self) -> str:
        return canonical_hash(self)

    def confidence(
        self,
        answer: Answer,
        question_id: str,
        language: Language,
        question_hash: str,
        *,
        engine_id: str,
        brand_hash: str,
        synthetic_engine: bool,
        allow_synthetic: bool = False,
    ) -> float | None:
        if engine_id != self.engine_id or brand_hash != self.brand_hash:
            return None
        if synthetic_engine and not allow_synthetic:
            return None
        if not synthetic_engine and self.provenance != "human_audited":
            return None
        cell = self.cells.get(f"{language}.{question_id}")
        if (
            cell is None
            or not cell.enabled
            or cell.threshold is None
            or cell.question_hash != question_hash
            or answer.abstained
        ):
            return None
        confidence = scale_confidence(answer.confidence, cell.temperature)
        return confidence if confidence >= cell.threshold else None


def scale_confidence(value: float, temperature: float) -> float:
    """FR-08: temperature on reported-confidence correctness logits, not vendor class logits."""
    probability = min(max(value, 1e-6), 1 - 1e-6)
    logit = math.log(probability / (1 - probability)) / temperature
    if logit >= 0:
        return 1 / (1 + math.exp(-logit))
    exponent = math.exp(logit)
    return exponent / (1 + exponent)


def ece(pairs: list[tuple[float, bool]], bins: int = 10) -> float | None:
    """FR-08: reliability error with closed final bin; empty language cells stay null."""
    if not pairs:
        return None
    error = 0.0
    for index in range(bins):
        bucket = [p for p in pairs if min(int(p[0] * bins), bins - 1) == index]
        if bucket:
            error += (
                len(bucket)
                / len(pairs)
                * abs(
                    sum(p[0] for p in bucket) / len(bucket)
                    - sum(p[1] for p in bucket) / len(bucket)
                )
            )
    return error


def wilson(correct: int, total: int) -> tuple[float, float] | None:
    """FR-08: observed precision carries an interval; it is not a guaranteed future rate."""
    if not total:
        return None
    p, z = correct / total, 1.96
    denominator = 1 + z * z / total
    middle = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0, middle - radius), min(1, middle + radius)


def split_groups(data: CalibrationData) -> dict[str, list[CalibrationCase]]:
    """NFR-03: EN/AR counterparts and repeated content stay together; split 60/20/20 groups."""
    groups = sorted(
        {c.group_id for c in data.cases},
        key=lambda group: canonical_hash({"seed": data.seed, "group": group}),
    )
    if len(groups) < 5:
        raise ValueError("Need at least five independent groups for a held-out split")
    n_train, n_val = int(0.6 * len(groups)), int(0.2 * len(groups))
    membership = {
        g: ("train" if i < n_train else "validation" if i < n_train + n_val else "test")
        for i, g in enumerate(groups)
    }
    return {
        name: [c for c in data.cases if membership[c.group_id] == name]
        for name in ("train", "validation", "test")
    }


def fit_calibration(
    data: CalibrationData,
    *,
    min_validation: int = 10,
    min_test: int = 10,
    target_precision: float = 0.95,
    max_escalation: float = 0.7,
) -> CalibrationProfile:
    """FR-08: fit solely on validation; test can disable a frozen threshold but never retune it."""
    if (
        min_validation < 1
        or min_test < 1
        or not 0 < target_precision <= 1
        or not 0 < max_escalation <= 1
    ):
        raise ValueError("Invalid fitting policy")
    split = split_groups(data)
    cells = {}
    buckets: dict[tuple[str, str], list[CalibrationCase]] = defaultdict(list)
    for c in data.cases:
        buckets[(c.language, c.question_id)].append(c)
    for (language, qid), all_cases in sorted(buckets.items()):
        hashes = {c.question_hash for c in all_cases}
        if len(hashes) != 1:
            raise ValueError("Question changed inside a calibration cell")
        validation = [
            c for c in split["validation"] if c.language == language and c.question_id == qid
        ]
        test = [c for c in split["test"] if c.language == language and c.question_id == qid]
        temperatures = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]

        def loss(t: float, rows: list[CalibrationCase] = validation) -> float:
            return sum(
                -math.log(
                    max(
                        1e-12,
                        scale_confidence(c.answer.confidence, t)
                        if c.correct
                        else 1 - scale_confidence(c.answer.confidence, t),
                    )
                )
                for c in rows
            )

        temperature = min(temperatures, key=lambda t: (loss(t), abs(t - 1))) if validation else 1.0
        pairs = [
            (scale_confidence(c.answer.confidence, temperature), c.correct)
            for c in validation
            if not c.answer.abstained
        ]
        threshold = None
        if len(validation) >= min_validation:
            for candidate in sorted({p for p, _ in pairs}):
                accepted = [correct for p, correct in pairs if p >= candidate]
                if (
                    len(accepted) >= min_validation
                    and sum(accepted) / len(accepted) >= target_precision
                ):
                    threshold = candidate
                    break
        accepted_test = [
            c
            for c in test
            if threshold is not None
            and not c.answer.abstained
            and scale_confidence(c.answer.confidence, temperature) >= threshold
        ]
        precision = (
            sum(c.correct for c in accepted_test) / len(accepted_test) if accepted_test else None
        )
        escalation = 1 - len(accepted_test) / len(test) if test else 1.0
        cells[f"{language}.{qid}"] = Cell(
            question_hash=next(iter(hashes)),
            temperature=temperature,
            threshold=threshold,
            validation_n=len(validation),
            test_n=len(test),
            accepted_test_n=len(accepted_test),
            precision=precision,
            precision_ci95=wilson(sum(c.correct for c in accepted_test), len(accepted_test)),
            accuracy=sum(c.correct for c in test) / len(test) if test else None,
            ece_before=ece([(c.answer.confidence, c.correct) for c in test]),
            ece_after=ece(
                [(scale_confidence(c.answer.confidence, temperature), c.correct) for c in test]
            ),
            escalation_rate=escalation,
            enabled=len(accepted_test) >= min_test
            and precision is not None
            and precision >= target_precision
            and escalation < max_escalation,
        )
    audited = [c for c in data.cases if c.human_gold is not None]
    agreement = sum(c.gold == c.human_gold for c in audited) / len(audited) if audited else None
    kappa: dict[str, float | None] = {}
    for language, qid in buckets:
        rows = [c for c in audited if c.language == language and c.question_id == qid]
        if not rows:
            kappa[f"{language}.{qid}"] = None
            continue
        categories = {repr(c.gold) for c in rows} | {repr(c.human_gold) for c in rows}
        expected = sum(
            sum(repr(c.gold) == label for c in rows)
            * sum(repr(c.human_gold) == label for c in rows)
            / len(rows) ** 2
            for label in categories
        )
        observed = sum(c.gold == c.human_gold for c in rows) / len(rows)
        kappa[f"{language}.{qid}"] = (
            (observed - expected) / (1 - expected) if expected < 1 else None
        )
    enabled = all(cell.enabled for cell in cells.values())
    return CalibrationProfile(
        engine_id=data.engine_id,
        brand_hash=data.brand_hash,
        provenance=data.provenance,
        dataset_hash=canonical_hash(data),
        split_items={name: sorted({c.item_id for c in rows}) for name, rows in split.items()},
        cells=cells,
        target_precision=target_precision,
        max_escalation=max_escalation,
        audit_agreement=agreement,
        audit_kappa=kappa,
        status="enabled"
        if enabled
        else "d1_only"
        if any(
            cell.enabled for key, cell in cells.items() if key.split(".")[1] in ("hook", "pillar")
        )
        else "disabled",
    )
