# Insta Bay

An approval-first Instagram marketing system for a fictional Red Sea resort in Hurghada.
The intended weekly loop is brand → plan → native EN/AR content → checks → human approval
→ publishing → metrics → learning. **LLMs write, statistics decide, a human approves.**

## Current status

Phase 3 adds a frozen seeded audience, factored Thompson sampling, long-format metrics,
transactional content-bound learning and a multi-week cycle. Phase 2 supplies the offline
weekly content loop: typed brand and post schemas,
SQLModel/SQLite storage, a constrained code planner, shared briefs, parallel native EN/AR
writers, tiered hashtags, deterministic rules, three judge samples, one revision,
a timed human approval CLI, guarded dry-run exports, and persistent LangGraph pause/resume.
The Phase 1 LLM cache, budgets, provenance, lint/type checks, hooks and CI remain in place.
Benchmarks, real publishing, System-1 engines and video rendering remain in their later
[specified phases](docs/SPEC.md). `make bench` and `make render` still exit with clear
phase-specific messages. No optimization uplift or model accuracy is claimed yet.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
make setup test lint
make smoke
make demo
uv run --offline --no-sync instabay approve --run-id 2026-w42 --actor YOUR_NAME
uv run --offline --no-sync instabay resume --run-id 2026-w42
```

Setup downloads the locked runtime and dependencies. Tests and lint use `uv --offline
--no-sync`; pytest blocks network sockets. No API keys, GPU or paid services are required.
Local hooks use the project's `.venv`, so they do not clone additional hook repositories.
If uv was bootstrapped locally in `.tools/bin/uv`, the Makefile detects it automatically.

`make demo` creates the fixed fixture week starting Monday 2026-10-12 (six feed posts and
one reel concept), displays EN/AR captions and checks, then **stops at human approval**.
It does not approve posts. The `approve` command asks approve/edit/reject for each post,
stores elapsed seconds and edit diffs, and requires a reason for flags and rejections.
`resume` reads those stored decisions and exports approved/edited posts as JSON into
`outbox/demo/`; rejected posts are skipped. Separate commands can run in separate processes.
Repeating a completed run returns its existing receipts without duplicate artifacts.

Demo SQLite state lives in `outputs/demo.sqlite3` and `outputs/demo-checkpoints.sqlite3`.
Use `--db`, `--checkpoints`, and `--outbox`, or `INSTABAY_DB_PATH`,
`INSTABAY_CHECKPOINTS_PATH`, and `INSTABAY_OUTBOX_PATH`, to select other paths.
Individual fixtures cover this demo run (`2026-w42`). The compact cycle catalog covers
`cycle-w01` through `cycle-w12`, with canned arm variants. Unknown slot keys fail explicitly.

The fixture brand remains **unfrozen** and the judge scores/token counts are illustrative,
not calibrated ratings or real model measurements. A new week uses 43 fixture requests:
1 brand, 7 briefs, 14 native copy requests and 21 judge samples. After approval, resumption
requires no new generation. Automated acceptance tests use marked synthetic approval
inputs in temporary databases; they never approve the normal demo's queue.

The reel outbox item is a **concept**, with shot descriptions, EN/AR overlays, audio intent,
CTA and cover reference. No video is rendered. All outbox items are dry-run intents marked
as reference-only and not ready for live media publishing.

## Multi-week synthetic cycle

```sh
uv run --offline --no-sync instabay cycle --weeks 3 --seed 7
uv run --offline --no-sync instabay approve --run-id cycle-w01 --actor YOUR_NAME
uv run --offline --no-sync instabay cycle --weeks 3 --seed 7
# HUMAN: review cycle-w02, rerun the same cycle, then review cycle-w03.
```

Each invocation resumes weeks with current stored human decisions, exports approved posts,
collects synthetic metrics, updates beliefs, and drafts the next week. It stops whenever
the current week needs approval. Rejections produce no export or metrics. The analyst
reports total engagement divided by total reach; these descriptive rates are not benchmark
results. Repeating a completed cycle returns its existing reports and learning receipts.

The simulator was frozen in commit `29fed9c` before any optimizer code. It uses a seeded
hidden audience with LogNormal reach, Binomial engagement and Beta reel watch-through.
Thompson sampling starts each factor level at Beta(1,1), and updates all four levels with
20 × engagement rate successes and 20 × (1 − rate) failures. The constrained planner keeps
pillar shares, at least one reel, posting windows and an exploration slot.

Learning requires content-bound fidelity evidence. This phase uses **synthetic fixture D1
labels for exact canned brief/copy replay**; it does not run or calibrate a decision engine.
Changed content remains unverified and is excluded from learning. Known arm leakage is also
excluded. Unverified edits receive clearly synthetic metrics assuming the planned arm, with
`arm_assumed=true`. Judge averages never authorize learning. Real D1 calibration waits for
Phase 6. Metrics, evidence and posterior updates are one SQLite transaction; interrupted
analysis and concurrent retries cannot update a post twice.

Beliefs are scoped by brand and audience seed/configuration. Cycle seed, dates, length,
brand inputs and fixture hashes are fixed at first invocation; changing them requires a
new cycle ID and matching fixture keys. The default pack has 12 weeks. To author a different
pack offline, copy the fixture directory, run `scripts/build_cycle_fixtures.py --cycle-id NAME
--weeks N --output PATH/cycle-catalog.json`, and pass `--fixtures PATH --cycle-id NAME`.
The authoring script enumerates every arm without consulting policy performance; replay only
reads canned JSON. Use separate SQLite/checkpoint/outbox paths for independent experiments.

See [the learning ADR](docs/adr/0003-phase3-learning-evidence.md) for synthetic assumptions
and [the phase report](docs/PHASE3_REPORT.md) for gate evidence. The 12-week, 20-seed baseline,
regret and confidence interval protocol belongs to Phase 4.

## Reproducibility and safety

Prompts are Markdown files; the AR copywriter prompt is written in Arabic. Cache keys include
the exact prompt hash, inputs, slot, model, output schema, temperature and token limit.
Invalid output gets one retry with sanitized validation feedback, then raises an error.
Only valid output within the run budget enters the cache. Corrupt cache entries are evicted.
The ledger records UTC times, tokens, cost, latency and safe error categories, without
prompts, input text, raw failed output or provider error messages.
Per-run usage is retained across graph restarts; parallel writers share call accounting.
Actual token/cost overrun is detected after a provider response, recorded, and halts the run;
a provider whose API does not expose preflight usage cannot guarantee an exact spend ceiling.

The default configuration is `dry_run`. Secrets belong in git-ignored `.env` or CI secrets;
`.env.example` contains empty credential fields. No real-provider adapter exists yet.
Dry-run publishing requires the **latest stored APPROVED/EDITED decision for the exact
content hash**. Changing content invalidates approval. SQLite holds a write transaction
across the guard, artifact write and receipt, so edits cannot race an export. Invalid hard-rule
edits are rejected. A graph resume payload cannot create approvals. No live adapter exists;
live environment mode is rejected by the demo/resume commands. System-1 is deferred to
Phase 6, so every post currently goes through rules and the fixture judge.

## Brand draft and human freeze

```sh
uv run --offline --no-sync instabay brand-draft
# HUMAN: edit the draft and save your constitution as config/brand.yaml.
uv run --offline --no-sync instabay brand-freeze --actor YOUR_NAME
```

The draft command writes `outputs/brand.draft.yaml` and refuses the reserved human file.
Only the explicit freeze command records a human actor and the constitution hash. The demo
does not create, edit or freeze `config/brand.yaml`. Non-demo storage runs require a frozen brand.

## Container demo

```sh
docker build -t instabay:phase3 .
docker run --rm --network none -v instabay-demo:/state instabay:phase3
docker run -it --rm --network none -v instabay-demo:/state instabay:phase3 approve --actor YOUR_NAME
docker run --rm --network none -v instabay-demo:/state instabay:phase3 resume
# Use a separate named volume for the multi-week cycle.
docker run --rm --network none -v instabay-cycle:/state instabay:phase3 cycle --weeks 3
docker run -it --rm --network none -v instabay-cycle:/state instabay:phase3 approve --run-id cycle-w01 --actor YOUR_NAME
docker run --rm --network none -v instabay-cycle:/state instabay:phase3 cycle --weeks 3
```

The image runs as UID 10001. Its `/state` volume preserves the queue, approval rows,
checkpoints and outbox across containers. Approval remains an interactive human step.

## Reference photography

The user-requested photo pack is tracked separately under `assets/photos/`. It depicts
**The Grand Resort Hurghada**, not an actual property named Insta Bay. Each asset has its
source, author, license, dimensions and SHA-256 in the manifest. Historical reference
photos do not establish current facilities or offers. See its attribution README before
using the photos or derivative footage. Video rendering and shot approval arrive in Phase 7.

## Human follow-up

- # HUMAN: run Phase 0 GPU/model spikes and record `docs/adr/0000-spikes.md`.
- # HUMAN: create provider keys and Meta tokens; record real LLM cassettes.
- # HUMAN: edit and freeze the brand constitution in Phase 2.
- # HUMAN: supply benchmark ratings in Phase 4.

The simulator must be committed separately **before** optimizer code is introduced.
