"""NFR-03, NFR-04, NFR-07: private recording and exact replay never hide failures."""

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest
from pydantic import ValidationError

from instabay.adapters.cassette import Cassette, RecordingLLMClient, ReplayLLMClient
from instabay.adapters.llm import Completion, CompletionRequest


def request(index=0):
    return CompletionRequest(
        template_name="copy_en",
        slot_id=f"case-{index}",
        model="recorded@" + "a" * 40,
        prompt="public prompt",
        prompt_hash=sha256(b"public prompt").hexdigest(),
        inputs={"angle": str(index)},
        output_schema={"type": "object"},
    )


class Client:
    calls = 0

    def complete(self, req):
        self.calls += 1
        return Completion(
            model=req.model,
            output_json='{"caption":"Visible water"}',
            input_tokens=10,
            output_tokens=5,
            cost_usd=0,
        )


def test_concurrent_recording_exact_replay_and_integrity(tmp_path):
    file = tmp_path / "cassette.json"
    live = Client()
    client = RecordingLLMClient(live, file)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(client.complete, [request(i) for i in range(8)]))
    finally:
        client.close()
    assert file.stat().st_mode & 0o777 == 0o600
    tape = Cassette.model_validate_json(file.read_bytes())
    assert len(tape.entries) == 8
    replay = ReplayLLMClient(file)
    for i in reversed(range(8)):
        assert replay.complete(request(i)).output_tokens == 5
    with pytest.raises(LookupError):
        replay.complete(request(0))
    changed = request(0).model_copy(update={"temperature": 1})
    with pytest.raises(LookupError):
        ReplayLLMClient(file).complete(changed)
    raw = json.loads(file.read_text())
    raw["entries"][0]["completion"]["output_json"] = "tampered"
    with pytest.raises(ValidationError, match="integrity"):
        Cassette.model_validate(raw)


def test_recording_rejects_credentials_before_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "never-expose-this-key")
    file = tmp_path / "private.json"
    live = Client()
    client = RecordingLLMClient(live, file)
    try:
        for inputs in [{"authorization": "anything"}, {"angle": "never-expose-this-key"}]:
            with pytest.raises(ValueError, match="Credential"):
                client.complete(request().model_copy(update={"inputs": inputs}))
        assert live.calls == 0 and not file.exists()
    finally:
        client.close()


def test_failed_provider_is_sanitized_and_not_replayed(tmp_path):
    class Failed:
        def complete(self, req):
            raise RuntimeError("private credential must never be saved")

    file = tmp_path / "private.json"
    client = RecordingLLMClient(Failed(), file)
    try:
        with pytest.raises(RuntimeError, match="raw exception omitted"):
            client.complete(request())
    finally:
        client.close()
    assert "private credential" not in file.read_text()
    assert Cassette.model_validate_json(file.read_bytes()).entries[0].status == "provider_error"
    with pytest.raises(LookupError):
        ReplayLLMClient(file).complete(request())


def test_recorder_single_writer_lock_released(tmp_path):
    file = tmp_path / "private.json"
    one = RecordingLLMClient(Client(), file)
    try:
        with pytest.raises(BlockingIOError):
            RecordingLLMClient(Client(), file)
    finally:
        one.close()
    two = RecordingLLMClient(Client(), file)
    two.close()


def test_record_command_is_resumable_and_rejects_public_capture(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from instabay.cli import app

    class Native(Client):
        def close(self):
            pass

    live = Native()
    monkeypatch.setattr("instabay.content.production_commands.native_client", lambda *args: live)
    source = tmp_path / "request.json"
    source.write_text(request().model_dump_json())
    destination = tmp_path / "capture.json"
    args = [
        "record",
        "--requests",
        str(source),
        "--model",
        request().model,
        "--output",
        str(destination),
    ]
    runner = CliRunner()
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.exception
    second = runner.invoke(app, args)
    assert second.exit_code == 0 and live.calls == 1
    source.write_text(request(1).model_dump_json())
    changed = runner.invoke(app, args)
    assert changed.exit_code != 0 and live.calls == 1
    bad = runner.invoke(
        app,
        [
            "record",
            "--requests",
            str(source),
            "--model",
            request().model,
            "--output",
            "tests/fixtures/private-capture.json",
        ],
    )
    assert bad.exit_code != 0 and "private cassettes" in bad.output


def test_private_capture_validation_errors_do_not_expose_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "private-value-that-must-not-appear")
    file = tmp_path / "bad.json"
    file.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"request": {"inputs": {"access_token": "private-value-that-must-not-appear"}}}
                ],
            }
        )
    )
    with pytest.raises(ValueError) as failure:
        ReplayLLMClient(file)
    assert "private-value-that-must-not-appear" not in str(failure.value)
    assert "private inputs omitted" in str(failure.value)
