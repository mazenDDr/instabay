#!/bin/sh
# NFR-07: run inside the prepared validation image with Docker --network none.
set -eu
mkdir -p outputs
if make setup demo test lint > outputs/clone-gate.log 2>&1; then
    cat outputs/clone-gate.log
else
    cat outputs/clone-gate.log
    exit 1
fi
.venv/bin/python scripts/check_clone_state.py
.venv/bin/pre-commit run --all-files
