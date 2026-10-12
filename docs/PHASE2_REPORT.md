# Phase 2 report

## 1. Built

- `core/schemas.py`, `core/tables.py`, `repository.py`: typed boundaries, SQLModel tables,
  normalized arm/run/slot relationships, native post copy, ordered tags, judge samples,
  append-only approvals and immutable dry-run receipts. Later-phase tables are schema only.
- `agents/`: Brand Architect, shared brief writer, parallel EN/AR writers and three-sample
  fixture judge with one Self-Refine pass. Initial failed judgments are retained.
- `core/planner.py`, `hashtags.py`, `rules.py`: integer pillar bounds, Cairo scheduling,
  minimum reels, explicit exploration, tiered hashtags, lengths/counts, Arabic ratio,
  banned terms and source-backed price/facility checks.
- `approval.py`, `cli.py`: bilingual review, timed approve/edit/reject, reasons and edit
  diffs; draft-only brand output and an explicitly human-invoked freeze command.
- `adapters/publisher.py`: publisher protocol, in-memory outbox fake and atomic file writer.
  Publishing requires the latest stored APPROVED/EDITED decision matching current content.
- `graph.py`: SQLite-checkpointed LangGraph with `interrupt()`, failed-draft recovery,
  stored-decision-only resume, rejection skipping and idempotent exports.
- Fixed seven-slot JSON fixtures, updated Markdown prompts and non-root Docker demo image.
- Shared concurrent LLM accounting and persisted run usage; a nullable run ID migration
  preserves the Phase 1 ledger and cache.

## 2. Gate evidence

| Check | Observed result |
|---|---|
| `make setup test lint` | Passed: 62 offline tests, Ruff clean, strict mypy clean in 29 source files |
| `make demo` with fresh gate state | 7 EN/AR drafts, 43 fixture requests, stopped at human approval |
| Persistent CLI integration | Separate demo/approve/resume invocations; edit/reject/approve path exported 6 intents |
| Fresh-runner integration | Stored synthetic approvals resumed 7 exports; retry stayed at 7 |
| Approval guards | Missing, rejected, stale or forged approvals blocked before outbox I/O |
| Planner property test | 50 arbitrary preference examples respected pillar/reel/quiet-hour limits |
| Parallel writer test | Both provider calls crossed a barrier; shared caps and ledger counts held |
| Phase 1 compatibility | Legacy usage rows and cached output survived the run-ID migration |
| Docker | Final image built; non-root, `--network none` acceptance run paused and resumed 7 intents |
| Original inputs | SPEC and the original photo pack remain byte-for-byte unchanged |

The Docker acceptance check and automated CLI tests use **synthetic test approvals in
isolated state**. They are not real content approvals. The normal fresh gate queue remains
at 7 drafts, 0 approvals and 0 exports. Judge scores and fixture token counts are illustrative;
no real LLM, Graph API, GPU, model-weight or video-render call was made.

The approval regression tests were committed in `c130649` before the publisher existed.
The publisher implementation followed in a later commit.

## 3. Deviations and ADR

[ADR 0002](adr/0002-phase2-approval-loop.md) records the phase boundaries. Neutral finite
preferences stand in for optimizer input; no bandit, simulator or posterior updates exist.
Rules go directly to the fixture judge until the calibrated System-1 phase. A reel is an
approved-content intent/concept rather than rendered footage, because Video Studio is
Phase 7. Reference photos remain identified as their real source resort. Human edits pass
deterministic rules; pre-edit judge samples are not relabeled as scores for edited content.
The demo constitution is explicitly unfrozen, and real brand editing/freezing remains human.

## 4. Human follow-up

- # HUMAN: review/merge the Phase 2 PR and authorize the next phase.
- # HUMAN: review the demo with `instabay approve --actor YOUR_NAME`, then run `instabay resume`.
- # HUMAN: edit the brand draft into `config/brand.yaml` and explicitly freeze it when ready.
- # HUMAN: Phase 0 spikes, real keys/tokens, cassette recording and benchmark ratings remain
  separate tasks for their specified phases. No GPU job is waiting or running from this phase.

## 5. Proposed next step

Phase 3: create and commit the seeded simulator **in a separate commit before any optimizer
code**, then add Thompson sampling, the analyst and `cycle --weeks N`. Stop here until the
human says next phase.
