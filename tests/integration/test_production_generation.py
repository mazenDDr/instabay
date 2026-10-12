"""FR-01, FR-09: real-workflow boundaries work offline without fabricated post approvals."""

import json
from datetime import date

import pytest
from typer.testing import CliRunner

from instabay.adapters.cassette import Cassette, RecordingLLMClient, ReplayLLMClient
from instabay.adapters.fake_llm import FakeLLM
from instabay.cli import app
from instabay.content.production import generate_week
from instabay.core.schemas import canonical_hash
from instabay.llm import RunBudget
from instabay.repository import Repository
from tests.unit.test_content_evidence import ROOT, campaign


def freeze_test_brand(output, brand):
    repo = Repository(output / "posts.sqlite")
    repo.register_brand(brand, actor="__synthetic_test_only__")
    repo.close()


def test_non_demo_record_resume_and_replay_stop_at_human_queue(tmp_path):
    brand, evidence, catalog, _ = campaign()
    output = tmp_path / "native"
    freeze_test_brand(output, brand)
    fake = FakeLLM(ROOT / "tests/fixtures/llm")
    recording = RecordingLLMClient(fake, output / "cassette.json")
    args = dict(
        brand=brand,
        evidence=evidence,
        catalog=catalog,
        root=ROOT,
        run_id="reference-w42",
        week_start=date(2026, 10, 12),
        model="fake-fixture-v1",
        budget=RunBudget(max_tokens=100000),
        draft_only=True,
    )
    try:
        result = generate_week(output=output, client=recording, **args)
        count = fake.calls
        repeated = generate_week(output=output, client=recording, **args)
        assert result == repeated and fake.calls == count == 21
    finally:
        recording.close()
    assert result.status == "approval_pending" and not (output / "outbox").exists()
    repo = Repository(output / "posts.sqlite")
    assert repo.run("reference-w42").demo is False
    assert all(repo.post(i).brand_hash == canonical_hash(brand) for i in result.post_ids)
    assert all(repo.latest_approval(i) is None for i in result.post_ids)
    repo.close()
    tape = Cassette.model_validate_json((output / "cassette.json").read_bytes())
    assert all(e.request.template_name != "brand_architect" for e in tape.entries)
    offline = tmp_path / "replayed"
    freeze_test_brand(offline, brand)
    replayed = generate_week(
        output=offline, client=ReplayLLMClient(output / "cassette.json"), replay=True, **args
    )
    assert replayed.status == "approval_pending" and not (offline / "outbox").exists()
    assert (
        json.loads((offline / "campaign.json").read_text())["generation_mode"] == "recorded_replay"
    )
    with pytest.raises(ValueError, match="Run inputs changed"):
        generate_week(
            output=offline,
            client=ReplayLLMClient(output / "cassette.json"),
            replay=True,
            **{**args, "model": "changed"},
        )


def test_unfrozen_brand_and_missing_motion_fail_before_calls(tmp_path):
    brand, evidence, catalog, _ = campaign()
    fake = FakeLLM(ROOT / "tests/fixtures/llm")
    args = dict(
        brand=brand,
        evidence=evidence,
        catalog=catalog,
        root=ROOT,
        output=tmp_path,
        run_id="reference-w42",
        week_start=date(2026, 10, 12),
        model="fake-fixture-v1",
        client=fake,
        budget=RunBudget(),
    )
    with pytest.raises(ValueError, match="human-frozen"):
        generate_week(**args)
    freeze_test_brand(tmp_path, brand)
    with pytest.raises(ValueError, match="Animate source photos"):
        generate_week(**args)
    assert fake.calls == 0


@pytest.mark.parametrize("command", ["generate", "record", "animate-photos"])
def test_generation_cli_cannot_use_live_mode(command, monkeypatch):
    monkeypatch.setenv("INSTABAY_MODE", "live")
    extra = {
        "generate": [
            "--brand",
            "config/brand.yaml",
            "--evidence",
            "config/reethi-faru-evidence.yaml",
            "--model",
            "x",
            "--run-id",
            "x",
            "--week-start",
            "2026-10-12",
        ],
        "record": ["--requests", "missing", "--model", "x"],
        "animate-photos": ["--scenes", "missing"],
    }
    result = CliRunner().invoke(app, [command, *extra[command]])
    assert result.exit_code != 0 and "dry_run" in result.output


def test_asset_pools_reach_the_writer_and_restrict_its_choices(tmp_path):
    brand, evidence, catalog, _ = campaign()
    ids = [o.id for o in catalog.objects]
    args = dict(
        brand=brand,
        evidence=evidence,
        catalog=catalog,
        root=ROOT,
        run_id="reference-w42",
        week_start=date(2026, 10, 12),
        model="fake-fixture-v1",
        budget=RunBudget(max_tokens=100000),
        draft_only=True,
    )
    output = tmp_path / "pooled"
    freeze_test_brand(output, brand)
    result = generate_week(
        output=output,
        client=FakeLLM(ROOT / "tests/fixtures/llm"),
        asset_pools=lambda slots: {s.id: ids for s in slots},
        **args,
    )
    pools = json.loads((output / "campaign.json").read_text())["asset_pools"]
    assert result.status == "approval_pending" and len(pools) == len(result.post_ids)
    narrowed = tmp_path / "narrowed"
    freeze_test_brand(narrowed, brand)
    with pytest.raises(ValueError):
        generate_week(
            output=narrowed,
            client=FakeLLM(ROOT / "tests/fixtures/llm"),
            asset_pools=lambda slots: {s.id: ["not-in-catalog"] for s in slots},
            **args,
        )
