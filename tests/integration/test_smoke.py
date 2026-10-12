"""NFR-03, NFR-07: offline CLI works across invocations with persistent cache."""

import socket
from pathlib import Path

import pytest
from pytest_socket import SocketBlockedError
from typer.testing import CliRunner

from instabay.cli import app
from instabay.db import SQLiteCallStore


def test_smoke_and_replay_use_no_live_provider(tmp_path: Path) -> None:
    runner = CliRunner()
    db = tmp_path / "calls.sqlite"
    first = runner.invoke(app, ["smoke", "--db", str(db)])
    assert first.exit_code == 0, first.output
    assert "Provider calls: 2" in first.output
    assert "متى" in first.output
    second = runner.invoke(app, ["smoke", "--db", str(db)])
    assert second.exit_code == 0, second.output
    assert "Provider calls: 0" in second.output
    with SQLiteCallStore(db) as store:
        assert [row.status for row in store.calls()] == ["success", "success", "cached", "cached"]


def test_later_phase_benchmark_command_does_not_claim_success() -> None:
    result = CliRunner().invoke(app, ["bench"])
    assert result.exit_code == 2
    assert "not implemented yet" in result.output


def test_network_sockets_are_blocked() -> None:
    with pytest.warns(UserWarning, match="socket.socket"), pytest.raises(SocketBlockedError):
        socket.socket()
