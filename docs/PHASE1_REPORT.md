# Phase 1 report

## 1. Built

- Python 3.12.15 uv project and lockfile; repository package layout, CLI and safe settings.
- `adapters/llm.py` protocol with Pydantic requests/completions and `FakeLLM` JSON replay.
- `llm.py` validation, one retry with sanitized feedback, request hashing and run budgets.
- `db.py` persistent SQLite cache and call ledger, with UTC records and metadata-only logs.
- EN/AR prompt files, worked-example fixtures and 31 offline tests.
- Ruff, strict mypy, local pre-commit hooks, offline secret scan, CI and pinned Docker image.
- Separate user-requested photo pack: four original JPEGs of The Grand Resort Hurghada,
  attribution, licensing, dimensions, hashes and visual-review notes in `assets/photos/`.
- Private GitHub repository and [PR #1](https://github.com/mazenDDr/instabay-agent/pull/1),
  with commits, committer identity and PR author verified as `mazenDDr`.

## 2. Gate evidence

| Command/check | Observed result |
|---|---|
| `make setup test lint` | Pass; hook installed, 31 tests passed, Ruff clean, strict mypy clean in 12 source files |
| `pre-commit run --all-files` | All hooks passed, including detect-secrets with network verification disabled |
| `make smoke` | EN/AR fixture captions generated; first run 2 calls, replay 0 calls |
| `docker build -t instabay:phase1 .` | Image built with pinned uv/Python base-image digests |
| `docker run --rm --network none instabay:phase1` | EN/AR smoke passed as UID 10001 with network disabled |
| Photo integrity | All 4 original sizes and SHA-256 hashes matched; images visually inspected |
| `.github/workflows/ci.yml` | Present; push and PR runs both passed on GitHub |
| Supplied specification | Byte-for-byte unchanged after relocating to `docs/SPEC.md` |

CI evidence: [pull-request run](https://github.com/mazenDDr/instabay-agent/actions/runs/38192801931)
and [push run](https://github.com/mazenDDr/instabay-agent/actions/runs/38192801903).
No real LLM calls, Graph API calls, model weights, GPU jobs or video renders were run.
Fixture usage and judge scores are illustrative, not model benchmarks.

## 3. Deviations and ADR

[ADR 0001](adr/0001-phase1-boundaries.md) records the decisions: relocate the supplied SPEC
to its documented path; keep business schemas, SQLModel and LangGraph for Phase 2; remove
unverified house-reef/room claims from illustrative fixtures; and have future-phase commands
exit explicitly until implemented. The reference photos are an additional user-authorized
retrieval task, with no video implementation added. Their real resort identity is retained.
Dependency setup requires network access; tests and lint execute offline.

## 4. Human follow-up

- # HUMAN: review/merge PR #1 and authorize the next phase.
- # HUMAN: edit and freeze the brand constitution in Phase 2.
- # HUMAN: run Phase 0 model/GPU spikes and record `docs/adr/0000-spikes.md` before Phases 6–7.
- # HUMAN: create provider keys/Meta tokens, record real LLM cassettes and provide ratings
  when their phases arrive. Real-photo keyframes still require normal shot approval.

## 5. Proposed next step

After the PR is accepted and the next phase is authorized, build Phase 2: schemas and
business storage, Brand Architect, Planner, shared briefs, native EN/AR writers, hashtags,
rules/judge, approval CLI, guarded DryRunPublisher and LangGraph `interrupt()`/resume.
Write the unapproved-publish test before implementing the publisher.
