"""FR-08: no split leakage, temperature/threshold fit on validation only, and fail-closed trust."""

import pytest

from instabay.core.schemas import canonical_hash
from instabay.decisions.calibration import (
    CalibrationCase,
    CalibrationData,
    ece,
    fit_calibration,
    scale_confidence,
    split_groups,
)
from instabay.decisions.engine import Answer


def dataset(provenance="synthetic", bad=False) -> CalibrationData:
    return CalibrationData(
        engine_id="fake-systemone-v1",
        brand_hash="a" * 64,
        provenance=provenance,
        cases=[
            CalibrationCase(
                item_id=f"{i}-{lang}",
                group_id=str(i),
                language=lang,
                state_hash=canonical_hash({"i": i, "lang": lang}),
                question_id="hook",
                question_hash="b" * 64,
                answer=Answer(choice="question", confidence=1 if bad else 0.99),
                gold="wrong" if bad else "question",
                human_gold="question" if i < 30 else None,
                human_actor="synthetic-test-human" if i < 30 else None,
            )
            for i in range(150)
            for lang in ("en", "ar")
        ],
    )


def test_grouped_split_counts_arabic_and_repeatability() -> None:
    data = dataset()
    split = split_groups(data)
    assert [len(split[n]) for n in ("train", "validation", "test")] == [180, 60, 60]
    groups = [{c.group_id for c in split[name]} for name in split]
    assert all(not groups[i] & groups[j] for i in range(3) for j in range(i))
    assert fit_calibration(data) == fit_calibration(data)


def test_test_and_train_labels_cannot_tune_validation_temperatures_or_thresholds() -> None:
    data = dataset()
    original = fit_calibration(data)
    validation = {c.item_id for c in split_groups(data)["validation"]}
    changed = data.model_copy(
        update={
            "cases": [
                c
                if c.item_id in validation
                else c.model_copy(update={"gold": "wrong", "human_gold": None, "human_actor": None})
                for c in data.cases
            ]
        }
    )
    alternate = fit_calibration(changed)
    for name, cell in original.cells.items():
        assert (cell.temperature, cell.threshold) == (
            alternate.cells[name].temperature,
            alternate.cells[name].threshold,
        )
        assert not alternate.cells[name].enabled


def test_synthetic_profile_never_trusted_by_native_engine_or_default() -> None:
    profile = fit_calibration(dataset())
    answer = Answer(choice="question", confidence=0.99)
    args = dict(engine_id=profile.engine_id, brand_hash=profile.brand_hash)
    assert (
        profile.confidence(
            answer, "hook", "ar", "b" * 64, synthetic_engine=False, allow_synthetic=True, **args
        )
        is None
    )
    assert profile.confidence(answer, "hook", "ar", "b" * 64, synthetic_engine=True, **args) is None
    assert (
        profile.confidence(
            answer, "hook", "ar", "b" * 64, synthetic_engine=True, allow_synthetic=True, **args
        )
        is not None
    )
    assert (
        profile.confidence(
            answer, "hook", "ar", "c" * 64, synthetic_engine=True, allow_synthetic=True, **args
        )
        is None
    )


def test_overconfident_failures_abstain_no_math_domain_error() -> None:
    profile = fit_calibration(dataset(bad=True))
    assert profile.status == "disabled"
    assert all(c.threshold is None and not c.enabled for c in profile.cells.values())
    assert ece([]) is None and ece([(1, False)]) == 1
    assert scale_confidence(0.01, 1e-6) == 0


def test_real_provenance_requires_minimum_items_arabic_and_audit() -> None:
    valid = dataset("human_audited")
    assert len(valid.cases) == 300
    with pytest.raises(ValueError):
        CalibrationData.model_validate({**valid.model_dump(), "cases": valid.cases[:200]})
    with pytest.raises(ValueError):
        CalibrationData.model_validate(
            {
                **valid.model_dump(),
                "cases": [
                    c.model_copy(update={"human_gold": None, "human_actor": None})
                    for c in valid.cases
                ],
            }
        )


def test_duplicate_text_across_groups_and_question_mutation_rejected() -> None:
    data = dataset()
    cases = data.cases.copy()
    cases[2] = cases[2].model_copy(update={"state_hash": cases[0].state_hash})
    with pytest.raises(ValueError):
        CalibrationData.model_validate({**data.model_dump(), "cases": cases})
    cases = data.cases.copy()
    cases[2] = cases[2].model_copy(update={"question_hash": "c" * 64})
    with pytest.raises(ValueError):
        fit_calibration(data.model_copy(update={"cases": cases}))


def test_calibration_cli_marks_synthetic_and_missing_labels_do_not_create_artifact(
    tmp_path,
) -> None:
    from typer.testing import CliRunner

    from instabay.cli import app

    data = tmp_path / "data.json"
    output = tmp_path / "profile.json"
    data.write_text(dataset().model_dump_json())
    result = CliRunner().invoke(
        app, ["calibrate-decisions", "--data", str(data), "--output", str(output)]
    )
    assert result.exit_code == 0 and "Synthetic evidence cannot enable" in result.output
    assert '"provenance": "synthetic"' in output.read_text()
    result = CliRunner().invoke(
        app,
        [
            "calibrate-decisions",
            "--data",
            str(tmp_path / "missing.json"),
            "--output",
            str(tmp_path / "missing-profile.json"),
        ],
    )
    assert result.exit_code == 2 and not (tmp_path / "missing-profile.json").exists()


def test_degenerate_human_label_kappa_is_null_not_invented_agreement() -> None:
    profile = fit_calibration(dataset())
    assert profile.audit_agreement == 1
    assert profile.audit_kappa == {"ar.hook": None, "en.hook": None}
