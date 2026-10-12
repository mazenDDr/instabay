"""NFR-04: dry-run is the only default, invalid modes fail at the boundary."""

import pytest
from pydantic import ValidationError

from instabay.settings import Settings


def test_default_is_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INSTABAY_MODE", raising=False)
    assert Settings.from_env().mode == "dry_run"


def test_typo_does_not_enable_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSTABAY_MODE", "LIVE")
    with pytest.raises(ValidationError):
        Settings.from_env()
