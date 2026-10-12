"""FR-06: HUMAN run on gpu-box; durable status around a bounded photo motion job."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """NFR-03: never repeat a started recipe after a process or transport failure."""
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["run", "status"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory
    status = directory / "status.json"
    if args.action == "status":
        print(status.read_text() if status.exists() else json.dumps({"state": "missing"}))
        return
    if os.environ.get("INSTABAY_GPU_ENABLED") != "1":
        raise PermissionError("GPU jobs require explicit opt-in")
    directory.mkdir(parents=True, exist_ok=True)
    claim = directory / "claim"
    with claim.open("x"):
        pass
    status.write_text(json.dumps({"state": "running"}) + "\n")
    with (directory / "worker.log").open("w") as log:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gpu_worker.wan_preview",
                "--spec",
                str(directory / "spec.json"),
                "--receipt",
                str(directory / "receipt.json"),
                "--confirm-gpu",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    receipt = (
        json.loads((directory / "receipt.json").read_text())
        if (directory / "receipt.json").exists()
        else None
    )
    status.write_text(
        json.dumps(
            {
                "state": "complete" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "receipt": receipt,
            }
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
