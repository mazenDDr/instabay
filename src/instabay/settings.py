"""NFR-04, NFR-07: safe defaults; no provider keys are required for offline work."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """NFR-04: validate execution mode before a later-phase adapter is selected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["dry_run", "live"] = "dry_run"
    db_path: Path = Path("outputs/instabay.sqlite3")

    @classmethod
    def from_env(cls) -> "Settings":
        """NFR-04: read only explicit non-secret environment settings."""
        return cls.model_validate(
            {
                "mode": os.environ.get("INSTABAY_MODE", "dry_run"),
                "db_path": os.environ.get("INSTABAY_DB_PATH", "outputs/instabay.sqlite3"),
            }
        )
