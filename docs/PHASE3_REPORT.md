# Phase 3 report

## 1. Built

- `sim/world.py`: independent hidden seeded audience, LogNormal reach, Binomial engagement,
  Beta reel watch-through and stable seed/event streams. Frozen fixture and simulator README.
  Commit `29fed9c` precedes all optimizer code; no simulator changes followed that commit.
- `core/optimizer.py` and `core/learning.py`: keyed factored Thompson samples, Beta(1,1)
  priors, typed measurements/evidence and the exact §15.9 pseudo-observation update.
- `adapters/insights.py`, `adapters/fixture_fidelity.py` and `agents/analyst.py`: swappable
  metrics/fidelity boundaries, synthetic insights, exact canned D1 label replay and code
  summaries. Known leaks and unverified edits never train the optimizer.
- SQLite long-format metrics, an immutable learning ledger, audience/brand-scoped posteriors,
  a preserving migration from the Phase 2 posterior table and immutable cycle configuration.
- `cycle.py`, CLI and planner wiring: `instabay cycle --weeks N`, with explicit human
  approval every week and recovery after process or insight-ingestion interruption.
- Compact canned catalog for 12 weeks and all 180 arms; explicit template+slot keys and
  native EN/AR examples. The offline authoring script does not consult either policy or
  simulator performance. README and Docker now include the cycle.

## 2. Gate evidence

| Check | Observed result |
|---|---|
| `make setup test lint` | 88 offline tests passed; Ruff clean; strict mypy clean in 37 source files |
| Planner property check | 100 seeds/posterior cases preserved shares, reels, windows, exploration and Cairo times |
| Seed replay | Two independent three-week runs had identical plans, metrics, reports and posterior states |
| Learning recovery | Same-post concurrent retry applied one update; injected second-factor failure rolled back everything |
| Approval/edit/reject integration | 13 exports across three weeks; 12 learned, one edited/unverified; rejected posts had no metrics |
| `docker build -t instabay:phase3 .` | Real pinned image built successfully |
| Docker acceptance, `--network none` | Three graph approval pauses; 21 synthetic-approved exports and learning receipts; retry unchanged |
| Fresh CLI review state | Seven drafts; zero approval, publication, metric, posterior or learning rows; no outbox directory |
| Preservation checks | SPEC and source resort photos unchanged; simulator unchanged since its first commit |

The Docker acceptance script inserts explicitly synthetic decisions only inside its
disposable container. Automated tests use temporary directories. No normal queue has been
approved by automation. The fresh local review command was:

```sh
.venv/bin/instabay cycle --weeks 3 \
  --db outputs/phase3-gate.sqlite3 \
  --checkpoints outputs/phase3-gate-checkpoints.sqlite3 \
  --outbox outbox/phase3-gate
```

Review that queue with `instabay approve --run-id cycle-w01 --actor YOUR_NAME --db
outputs/phase3-gate.sqlite3`, then rerun the exact cycle command to export, learn and draft
week 2. Repeat for each weekly queue. Cycle arguments and fixture hashes are immutable;
larger or differently named cycles require an explicitly authored fixture pack.

## 3. Deviations and decisions

[ADR 0003](adr/0003-phase3-learning-evidence.md) records the synthetic fidelity bridge until
Phase 6, the compact strict fixture catalog, scoped/idempotent learning and logical
simulation timestamps. Fixture D1 labels verify wiring only; they do not establish real
engine accuracy or calibration. The analyst is deterministic code rather than an optional
LLM explanation. Unknown edited arms receive assumed-planned synthetic metrics and are
excluded from learning. The full 12-week/20-seed policy comparison and confidence intervals
are reserved for Phase 4; this phase makes no uplift claim.

## 4. HUMAN items

- # HUMAN: review the PR and merge it when ready.
- # HUMAN: approve/edit/reject any draft you want exported; no decision was synthesized in
  the real review state. Edit/freeze the real brand separately before non-demo operation.
- # HUMAN: collect real D1 ratings/calibration data and GPU spike numbers before Phases 6/7.
  Tailscale and SSH connectivity were checked; no GPU job was started.

## 5. Proposed next step

After merge and explicit authorization, Phase 4 builds the five-metric benchmark harness,
fixed/random/Thompson/oracle policies, paired intervals and the README table generator.
Stop at this phase gate until the human says to continue.
