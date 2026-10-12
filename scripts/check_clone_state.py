"""FR-09, NFR-07: verify real clone/demo evidence, never manufacture approvals."""

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path


def main() -> None:
    """FR-09: a successful command must also leave a persistent unapproved checkpoint."""
    root = Path.cwd()
    db = root / os.environ["INSTABAY_DB_PATH"]
    checkpoints = root / os.environ["INSTABAY_CHECKPOINTS_PATH"]
    outbox = root / os.environ["INSTABAY_OUTBOX_PATH"]
    assert os.getuid() == 10001, "Validation must use the unprivileged runtime user"
    assert (root / ".git").exists(), "Validation needs a committed checkout for hooks"
    assert not (root / ".env").exists(), "Personal credentials must not enter the image"
    assert db.is_file() and checkpoints.is_file(), "Absent files are not evidence of a safe stop"
    with sqlite3.connect(db) as connection:
        counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ["post", "approval", "publication", "metric", "posterior", "render_job"]
        }
    assert counts["post"] == 7
    assert all(
        counts[t] == 0 for t in ["approval", "publication", "metric", "posterior", "render_job"]
    )
    assert not outbox.exists(), "The default demo must create no outbox before approval"
    log = (root / "outputs/clone-gate.log").read_text()
    assert "STOPPED at human approval" in log
    passed = re.search(r"\b(\d+) passed\b", log)
    assert passed is not None, "Offline test evidence is missing"
    import yaml

    from instabay.core.schemas import BrandInput
    from instabay.graph import WeekRunner

    inputs = BrandInput.model_validate(
        yaml.safe_load((root / "config/brand_inputs.example.yaml").read_text())
    )
    with WeekRunner(db, checkpoints, outbox, inputs) as runner:
        assert runner.result("2026-w42").status == "approval_pending"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    evidence = {
        "checkout_head": head,
        "uid": os.getuid(),
        "mode": "dry_run",
        "tests_passed": int(passed.group(1)),
        "demo_status": "approval_pending",
        "counts": counts,
        "outbox_exists": False,
        "native_inference": False,
    }
    (root / "outputs/clone-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
