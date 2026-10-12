"""NFR-07: test processes do not need tokens or live mode."""

import pytest


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """NFR-07: clear provider credentials; pytest-socket blocks every network socket."""
    for key in (
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "INSTAGRAM_ACCESS_TOKEN",
        "GH_TOKEN",
        "INSTABAY_SYSTEMONE_API_KEY",
        "INSTABAY_DECISIONS_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INSTABAY_MODE", "dry_run")
