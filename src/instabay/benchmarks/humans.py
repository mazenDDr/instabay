"""FR-14: blind-rating ingestion, exact corpus binding, and missing-data handling."""

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Literal, Self

from pydantic import Field, model_validator

from instabay.adapters.fixture_fidelity import content_signature
from instabay.benchmarks.models import (
    ArabicMetric,
    ArabicScores,
    AutonomyMetric,
    BrandMetric,
    ContentEvidence,
    HumanTouchpoint,
)
from instabay.benchmarks.policies import keyed_rng
from instabay.benchmarks.statistics import (
    bootstrap,
    krippendorff_alpha,
    quadratic_kappa,
    spearman,
)
from instabay.core.schemas import Boundary, Hash, Identifier, RubricScores, UTCDateTime

DIMENSIONS = ("voice", "pillar_fit", "caption_visual_match", "hashtag_policy", "format_cta")


class TranslationCase(Boundary):
    """FR-14: authored literal-translation fixtures are not real recorded MT calls."""

    post_id: Identifier
    caption: str = Field(min_length=1)
    provenance: Literal["authored_fixture_translation", "recorded_mt"] = (
        "authored_fixture_translation"
    )
    english_source_hash: Hash | None = None
    model: str | None = None
    recorded_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def recorded_metadata(self) -> Self:
        if self.provenance == "recorded_mt" and (
            not self.english_source_hash
            or not self.model
            or not self.model.strip()
            or not self.recorded_at
        ):
            raise ValueError("Recorded MT needs source hash, model and UTC recording timestamp")
        return self


class BlindItem(Boundary):
    """FR-14: opaque IDs and caption hashes bind returned ratings to exact text."""

    item_id: Identifier
    post_id: Identifier
    version: Literal["native", "mt"]
    caption: str
    content_signature: Hash
    provenance: str = "fixture"


class BrandRating(RubricScores):
    """FR-14: all five anchored integer dimensions are required together."""

    post_id: Identifier
    content_signature: Hash
    rater_id: Identifier


class ArabicRating(ArabicScores):
    """FR-14: raters see only opaque item IDs and captions, not the native/MT key."""

    item_id: Identifier
    content_signature: Hash
    rater_id: Identifier


class ApprovalFeedback(Boundary):
    """FR-14: human timing/decisions for analysis only; never inserts an approval row."""

    post_id: Identifier
    content_signature: Hash
    decision: Literal["APPROVED", "EDITED", "REJECTED"]
    seconds_spent: float = Field(ge=0)
    reason: str = Field(min_length=1)


def _read_rows(
    directory: Path, pattern: str, score_fields: tuple[str, ...]
) -> list[dict[str, str]]:
    result = []
    for path in sorted(directory.glob(pattern)):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if None in row:
                    raise ValueError("Malformed human CSV column count")
                cleaned = {key: (value or "").strip() for key, value in row.items()}
                if not any(cleaned.get(field) for field in score_fields):
                    continue  # Unfilled HUMAN template is pending data, not a zero score.
                if any(not cleaned.get(field) for field in score_fields):
                    raise ValueError("Partially filled human rating row")
                result.append(cleaned)
    return result


def blind_packet(
    content: list[ContentEvidence], translations: list[TranslationCase]
) -> list[BlindItem]:
    """FR-14: exactly 20 native + 20 fixture translations, deterministically shuffled."""
    selected = content[:20]
    lookup = {case.post_id: case for case in translations}
    if len(lookup) != 20 or set(lookup) != {row.post.id for row in selected}:
        raise ValueError("Translation fixtures must cover exactly the first 20 frozen posts")
    items = []
    for evidence in selected:
        for version in ("native", "mt"):
            caption = (
                evidence.post.ar.caption
                if version == "native"
                else lookup[evidence.post.id].caption
            )
            translation = lookup[evidence.post.id]
            if (
                version == "mt"
                and translation.provenance == "recorded_mt"
                and translation.english_source_hash
                != hashlib.sha256(evidence.post.en.caption.encode()).hexdigest()
            ):
                raise ValueError("Recorded MT does not bind to the exact English source")
            signature = hashlib.sha256(caption.encode()).hexdigest()
            opaque = hashlib.sha256(
                f"blind-v1:{evidence.post.id}:{version}:{signature}".encode()
            ).hexdigest()[:16]
            items.append(
                BlindItem(
                    item_id=f"item-{opaque}",
                    post_id=evidence.post.id,
                    version=version,
                    caption=caption,
                    content_signature=signature,
                    provenance="fixture_native" if version == "native" else translation.provenance,
                )
            )
    keyed_rng(42, "blind-packet").shuffle(items)
    return items


def write_packet(root: Path, content: list[ContentEvidence], items: list[BlindItem]) -> None:
    """FR-14: only untouched templates are rewritten; returned human CSVs live elsewhere."""
    root.mkdir(parents=True, exist_ok=True)
    arabic_template = root / "arabic_template.csv"
    if not arabic_template.exists():
        _write_arabic_template(arabic_template, items)
    # Captions are separate so they cannot accidentally become an extra CSV rating field.
    (root / "arabic_blind_items.json").write_text(
        json.dumps(
            [{"item_id": item.item_id, "caption": item.caption} for item in items],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "arabic_key_private.json").write_text(
        json.dumps([item.model_dump() for item in items], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for name, fields in (
        ("brand", ["post_id", "content_signature", "rater_id", *DIMENSIONS]),
        ("approval", ["post_id", "content_signature", "decision", "seconds_spent", "reason"]),
    ):
        path = root / f"{name}_template.csv"
        if path.exists():
            continue
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            selected = content[:20] if name == "brand" else content
            writer.writerows(
                {"post_id": row.post.id, "content_signature": content_signature(row.post)}
                for row in selected
            )


def _write_arabic_template(path: Path, items: list[BlindItem]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "item_id",
                "content_signature",
                "rater_id",
                "fluency",
                "naturalness",
                "brand_voice",
            ],
        )
        writer.writeheader()
        writer.writerows(
            {"item_id": item.item_id, "content_signature": item.content_signature} for item in items
        )


def brand_metric(
    content: list[ContentEvidence], negative_scores: list[float], ratings_dir: Path
) -> BrandMetric:
    """FR-14: QWK uses pooled anchored post/dimension pairs after per-post rater averaging."""
    labels = [
        BrandRating.model_validate(row)
        for row in _read_rows(ratings_dir, "brand_*.csv", DIMENSIONS)
    ]
    corpus = {row.post.id: row for row in content[:20]}
    grouped: dict[str, list[BrandRating]] = defaultdict(list)
    seen = set()
    for label in labels:
        if label.post_id not in corpus or label.content_signature != content_signature(
            corpus[label.post_id].post
        ):
            raise ValueError("Brand rating does not match the frozen corpus")
        key = (label.post_id, label.rater_id)
        if key in seen:
            raise ValueError("Duplicate brand rater/post")
        seen.add(key)
        grouped[label.post_id].append(label)
    human, judge = [], []
    for post_id, rows in grouped.items():
        samples = corpus[post_id].review.judge.samples
        for dimension in DIMENSIONS:
            # Round halves upward, consistently, on the anchored 1..5 category scale.
            human.append(int(mean(getattr(row, dimension) for row in rows) + 0.5))
            judge.append(int(mean(getattr(sample.scores, dimension) for sample in samples) + 0.5))
    scores = [row.review.judge.average for row in content]
    control = bootstrap(negative_scores)
    gap = bootstrap([scores[index] - score for index, score in enumerate(negative_scores)])
    return BrandMetric(
        judge_mean=bootstrap(scores),
        hard_rule_pass_rate=bootstrap([float(row.review.rules.passed) for row in content]),
        negative_control_mean=control,
        negative_control_gap=gap,
        negative_control_clearly_lower=gap.low > 0,
        quadratic_weighted_kappa=quadratic_kappa(human, judge) if human else None,
        labeled_posts=len(grouped),
        calibration_status=(
            "human_labels_available"
            if len(grouped) == 20
            else "partial_human"
            if grouped
            else "pending_human"
        ),
    )


def arabic_metric(
    content: list[ContentEvidence], items: list[BlindItem], ratings_dir: Path
) -> ArabicMetric:
    """FR-14: paired native/MT means, tie-half wins, interval alpha and tied Spearman."""
    labels = [
        ArabicRating.model_validate(row)
        for row in _read_rows(
            ratings_dir, "arabic_*.csv", ("fluency", "naturalness", "brand_voice")
        )
    ]
    lookup = {item.item_id: item for item in items}
    grouped: dict[str, list[ArabicRating]] = defaultdict(list)
    seen = set()
    for label in labels:
        if (
            label.item_id not in lookup
            or label.content_signature != lookup[label.item_id].content_signature
        ):
            raise ValueError("Arabic rating does not match the exact blind caption")
        key = (label.item_id, label.rater_id)
        if key in seen:
            raise ValueError("Duplicate Arabic rater/item")
        seen.add(key)
        grouped[label.item_id].append(label)
    means: dict[tuple[str, str], float] = {
        (lookup[item_id].post_id, lookup[item_id].version): mean(row.average for row in rows)
        for item_id, rows in grouped.items()
    }
    native = [value for (post_id, version), value in means.items() if version == "native"]
    mt = [value for (post_id, version), value in means.items() if version == "mt"]
    pairs = [
        (means[(row.post.id, "native")], means[(row.post.id, "mt")])
        for row in content[:20]
        if (row.post.id, "native") in means and (row.post.id, "mt") in means
    ]
    human, judge = [], []
    for row in content[:20]:
        if (row.post.id, "native") in means:
            human.append(means[(row.post.id, "native")])
            judge.append(mean(sample.average for sample in row.arabic_samples))
    return ArabicMetric(
        judge_mean=bootstrap(
            [mean(sample.average for sample in row.arabic_samples) for row in content]
        ),
        native_mean=bootstrap(native) if native else None,
        mt_mean=bootstrap(mt) if mt else None,
        native_win_rate=bootstrap([1.0 if a > b else 0.5 if a == b else 0.0 for a, b in pairs])
        if pairs
        else None,
        krippendorff_alpha_interval=krippendorff_alpha(
            [[r.average for r in rows] for rows in grouped.values()]
        ),
        judge_human_spearman=spearman(human, judge),
        rated_items=len(grouped),
        unique_native_captions=len({item.caption for item in items if item.version == "native"}),
        unique_translation_captions=len({item.caption for item in items if item.version == "mt"}),
        paired_posts=len(pairs),
        raters=len({row.rater_id for row in labels}),
        status=(
            "human_labels_available"
            if len(pairs) == 20
            else "partial_human"
            if labels
            else "pending_human"
        ),
        comparison_provenance=(
            "recorded_mt; native captions still fixture examples"
            if all(item.provenance == "recorded_mt" for item in items if item.version == "mt")
            else "authored_fixture_translation; not a real MT-provider evaluation"
        ),
    )


def autonomy_metric(content: list[ContentEvidence], ratings_dir: Path) -> AutonomyMetric:
    """FR-14: incomplete approval-gated content benchmark cannot claim operational autonomy."""
    labels = [
        ApprovalFeedback.model_validate(row)
        for row in _read_rows(
            ratings_dir, "approval_*.csv", ("decision", "seconds_spent", "reason")
        )
    ]
    corpus = {row.post.id: row for row in content}
    seen = set()
    minutes: dict[str, list[float]] = defaultdict(list)
    for row in labels:
        if row.post_id not in corpus or row.content_signature != content_signature(
            corpus[row.post_id].post
        ):
            raise ValueError("Approval feedback does not match the frozen corpus")
        if row.post_id in seen:
            raise ValueError("Duplicate first-pass approval feedback")
        seen.add(row.post_id)
        minutes[corpus[row.post_id].slot.run_id].append(row.seconds_spent / 60)
    complete = len(labels) == len(content)
    weeks = len({row.slot.run_id for row in content})
    return AutonomyMetric(
        configured_steps=8 * weeks,
        automatic_steps=7 * weeks,
        configured_automation_share=7 / 8,
        observed_completed_automatic_steps=4 * weeks,
        pending_human_steps=weeks,
        blocked_downstream_steps=3 * weeks,
        human_minutes_per_week=bootstrap([sum(values) for values in minutes.values()])
        if complete
        else None,
        first_pass_approval_rate=bootstrap([float(row.decision == "APPROVED") for row in labels])
        if complete
        else None,
        touchpoints=[
            HumanTouchpoint(
                post_id=row.post_id,
                decision=row.decision,
                reason=row.reason,
                seconds_spent=row.seconds_spent,
            )
            for row in labels
        ],
        status="no_publish; timing feedback complete" if complete else "pending_human_timing",
    )
