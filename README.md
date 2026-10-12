# Insta Bay

The new [coastal mixed-week preview](docs/samples/coastal-week/README.md) uses source-grounded
scenic reels, three single photographs and two real carousels, with EN/AR captions.
See [content direction and generation limits](docs/CONTENT_DIRECTION.md).
Run `uv run instabay reference-week` for the offline mixed-format draft and local review gallery;
it stops at human approval and never publishes the historical reference property.

An approval-first Instagram marketing system for a fictional Red Sea resort in Hurghada.
The intended weekly loop is brand → plan → native EN/AR content → checks → human approval
→ publishing → metrics → learning. **LLMs write, statistics decide, a human approves.**

## Current status

The offline prototype includes a resumable weekly content loop, mandatory exact-content human
approval, constrained Thompson sampling, a frozen simulator, five-metric benchmark harness,
guarded Instagram adapters, scoped decision calibration and a recipe-cached Video Studio.
**327 offline tests** cover the software boundaries. A synthetic 15-second CPU reel renders at
1080×1920/30 fps; uncached replay matches all 450 decoded frames on its tested runtime.

The default demo uses canned `FakeLLM` responses. Real local generation is also implemented:
[production drafting](docs/PRODUCTION_GENERATION.md) loads an already human-frozen brand,
animates approved photographs, generates mixed EN/AR posts, records/replays native calls and
stops at approval. The owner accepted the demonstrated photo-to-video direction. Instagram,
live learning and calibrated quality claims remain pending; reference media stays protected.
No acceptance of a demo is converted into a stored publication approval.
See [native generation and offline replay evidence](docs/production-generation-verification.json).

Phase 8 provides the documentation and reproducible fresh-clone Docker gate. Read
[architecture](docs/ARCHITECTURE.md), [research](docs/RESEARCH.md), [go-live prerequisites](docs/GO_LIVE.md),
[remaining work](docs/BACKLOG.md), [decision details](docs/DECISIONS.md), [video usage](docs/VIDEO.md),
[ADRs](docs/adr/README.md) and [Phase 8 evidence](docs/PHASE8_REPORT.md).
This prototype exceeds the original 5–6 hour guideline; an audited total effort was not recorded.
The implementation/evidence boundaries are stated so the take-home can be assessed honestly.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
make setup test lint
make smoke
make demo
uv run --offline --no-sync instabay approve --run-id 2026-w42 --actor YOUR_NAME
uv run --offline --no-sync instabay resume --run-id 2026-w42
```

Install ffmpeg/ffprobe for the video tests (the Docker images and CI include them).
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

The default reel outbox item is a **concept**, with shot descriptions, EN/AR overlays, audio intent,
CTA and cover reference. `instabay demo --render-reels` additionally renders a clearly marked
synthetic preview before checks and human approval. All outbox items are dry-run intents marked
as reference-only and not ready for live media publishing.

For a standalone offline preview and uncached decoded-frame comparison:

```sh
make render RECIPE=config/recipes/stub.shotlist.json BACKEND=stub
make golden RECIPE=config/recipes/stub.shotlist.json BACKEND=stub
```

Install ffmpeg/ffprobe first. Every artifact directory stores its complete recipe, result,
decoded-frame hashes and contact sheet. Missing semantic/continuity evidence stays flagged.
The supplied still is abstract fixture art; source-resort photos still need human crop approval.

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

Learning requires content-bound fidelity evidence. The offline cycle uses **synthetic fixture D1
labels for exact canned brief/copy replay**; it does not run or calibrate a decision engine.
Changed content remains unverified and is excluded from learning. Known arm leakage is also
excluded. Unverified edits receive clearly synthetic metrics assuming the planned arm, with
`arm_assumed=true`. Judge averages never authorize learning. Real D1 calibration requires
recorded labels and human audits. Metrics, evidence and posterior updates are one SQLite transaction; interrupted
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
regret and confidence interval protocol is implemented in the benchmark harness below.

## Benchmarks

Run `make bench` for all five metric rows, policy comparisons and the generated results
table. The offline command writes `bench/results.json`, intermediate evidence and blinded
rating templates under `outputs/bench/`. It never approves or publishes drafts. Human
ratings, actual model quality, real provider prices and operational autonomy remain
pending when evidence is missing. The results below are from canned quality fixtures
and the unchanged synthetic audience.

<!-- BENCHMARK:START -->
| Metric | Result (95% interval where shown) | Evidence / limitation |
|---|---|---|
| Brand consistency | 4.60 [4.60, 4.60] / 5; hard rules 100.00% [100.00, 100.00] | Canned judge, κ pending human labels; (0/20 posts); control 2.20 [2.20, 2.20] / 5 |
| Arabic quality | Human native: Pending human ratings; MT: pending; native win: pending | Canned judge 4.67 [4.67, 4.67] / 5; 0/20 human pairs; interval alpha undefined/pending; authored MT fixtures; no real-model quality claim |
| Optimization uplift | 68.20% [37.77, 114.14] | Synthetic Thompson vs fixed week-1; weeks 9-12; 20 paired seeds |
| Efficiency | feed: 1080 in/490 out tokens; local p50/p95 6.79/7.33 ms; actual $0.0000/post; paid pending; reel_concept: 1080 in/490 out tokens; local p50/p95 6.87/7.71 ms; actual $0.0000/post; paid pending | Fixture tokens/local timing; 0 video renders |
| Autonomy | Pending human timing; configured automation 87.5%; first-pass approval pending | Topology only; full pipeline measurement pending approval; bench never publishes |

Policy comparison (synthetic audience; seed-cluster intervals):

| Policy | Weeks 9-12 engagement rate | Cumulative expected regret | Leaked / learned posts |
|---|---|---|---|
| fixed | 4.85% [3.63, 6.19] | 4.69 [3.72, 5.81] | 0 / 0 |
| uniform | 4.92% [4.26, 5.64] | 4.53 [3.70, 5.42] | 0 / 0 |
| thompson | 8.15% [7.06, 9.23] | 2.66 [2.22, 3.17] | 0 / 1680 |
| oracle | 10.43% [9.20, 11.75] | 0.00 [0.00, 0.00] | 0 / 0 |
| leak_unguarded | 7.83% [6.69, 8.92] | 2.87 [2.40, 3.41] | 301 / 1680 |
| leak_guarded | 7.78% [6.66, 8.87] | 2.95 [2.45, 3.53] | 301 / 1379 |

Synthetic D1-on minus D1-off regret: 0.08 [-0.04, 0.21]. Negative favors the guard; an interval crossing zero does not establish a difference.

Generated from [bench/results.json](bench/results.json). [Protocol, rubric and HUMAN steps](bench/README.md). Canned rubric/control scores test the harness; they do not establish real judge accuracy.
<!-- BENCHMARK:END -->

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
`.env.example` contains empty credential fields. Native Graph publishing and insights adapters
are available for HUMAN-invoked, prepared non-demo posts. The opt-in local LLM adapter and
private recording/replay are implemented; Instagram integration remains pending.
Dry-run publishing requires the **latest stored APPROVED/EDITED decision for the exact
content hash**. Changing content invalidates approval. SQLite holds a write transaction
across the guard, artifact write and receipt, so edits cannot race an export. Invalid hard-rule
edits are rejected. A graph resume payload cannot create approvals. The demo/resume/cycle
commands reject live mode. Explicit native Graph commands require live mode, environment
credentials, `--confirm-live`, a frozen brand, approved ready media and a matching stored
approval. [Behavior, retry limits and HUMAN steps](docs/INSTAGRAM.md). [Phase 6 decision checks](docs/DECISIONS.md) support opt-in scoped calibration; the default
continues through rules and the fixture judge until real evidence exists.

## Decision checks

Typed HTTP/local engines, per-language calibration, selective escalation context, reproducible
10% audits and content-bound D1 evidence are available. System-1-only reviews have no invented
rubric scores. Engine outages, uncalibrated/mismatched profiles and adverse answers fall back
to the judge; human approval always remains. [Usage and HUMAN data requirements](docs/DECISIONS.md),
[Phase 6 evidence](docs/PHASE6_REPORT.md). No real model accuracy or savings are claimed.

## Instagram adapters

Phase 5 adds approval-guarded photo, image-carousel and reel URL publishing, a durable
SQLite operation journal and parent-media insights. Unknown POST outcomes stop for human
reconciliation; a known receipt is reused without another request. Empty/partial insight
batches keep missing values missing. Live counts are stored without updating bandit beliefs.
The contracts are synthetic and run offline; no live Instagram post has been verified.
See [usage and limitations](docs/INSTAGRAM.md) and [Phase 5 evidence](docs/PHASE5_REPORT.md).

## Brand draft and human freeze

```sh
uv run --offline --no-sync instabay brand-draft
# HUMAN: edit the draft and save your constitution as config/brand.yaml.
uv run --offline --no-sync instabay brand-freeze --actor YOUR_NAME
```

The draft command writes `outputs/brand.draft.yaml` and refuses the reserved human file.
Only the explicit freeze command records a human actor and the constitution hash. The demo
does not create, edit or freeze `config/brand.yaml`. Non-demo storage runs require a frozen brand.

## Fresh-clone gate

```sh
# HUMAN: confirm gh reports mazenDDr before accessing this private repository.
gh api user --jq .login
gh repo clone mazenDDr/instabay-agent instabay-clean
cd instabay-clean
make verify-clone
```

The validation image prepares locked dependencies from that checkout, retains its Git metadata
for hooks, and runs `make setup demo test lint` as UID 10001 with networking disabled. It verifies
seven normal-demo drafts, a persistent approval stop, zero approvals/publications/metrics/beliefs
and no outbox. Tests use disposable synthetic approvals only. Evidence is generated inside the
container at `outputs/clone-evidence.json`. The validation image contains dev tools; the normal
runtime image below remains separate. Personal caches, state, `.env` and ratings are excluded.

## Container demo

```sh
docker build -t instabay:phase8 .
docker run --rm --network none -v instabay-demo:/state instabay:phase8
docker run -it --rm --network none -v instabay-demo:/state instabay:phase8 approve --actor YOUR_NAME
docker run --rm --network none -v instabay-demo:/state instabay:phase8 resume
# Use a separate named volume for the multi-week cycle.
docker run --rm --network none -v instabay-cycle:/state instabay:phase8 cycle --weeks 3
docker run -it --rm --network none -v instabay-cycle:/state instabay:phase8 approve --run-id cycle-w01 --actor YOUR_NAME
docker run --rm --network none -v instabay-cycle:/state instabay:phase8 cycle --weeks 3
docker run --rm --network none -v instabay-bench:/state instabay:phase8 bench
```

The image runs as UID 10001. Its `/state` volume preserves the queue, approval rows,
checkpoints and outbox across containers. Approval remains an interactive human step.

## Reference photography

The user-requested photo pack is tracked separately under `assets/photos/`. It depicts
**The Grand Resort Hurghada**, not an actual property named Insta Bay. Each asset has its
source, author, license, dimensions and SHA-256 in the manifest. Historical reference
photos do not establish current facilities or offers. See its attribution README before
using the photos or derivative footage. Phase 7 preserves their original bytes and approval flags;
the offline video gate uses a synthetic still. The user approved crops for an unpublished sample
on 2026-10-12. Original-photo approval flags remain unchanged; derivative crop evidence is separate.

Real local caption generation and a measured photo-conditioned Wan preview are described in
[NATIVE_PREVIEW.md](docs/NATIVE_PREVIEW.md). These optional runs use gpu-box and remain separate
from offline demos, calibrated benchmarks, brand freezing and post approval.

## Human follow-up

- # HUMAN: record actual GPU/Laya/FLF/runtime spikes in `docs/adr/0000-spikes.md`.
- # HUMAN: create provider/Meta keys, freeze verified brand facts and approve photo crops.
- # HUMAN: provide independent benchmark/calibration labels and native video QA.
- # HUMAN: native recording is available through `make record ARGS="..."`; captures remain private.
- # HUMAN: approve the next backlog/deployment scope; no native job or live publish starts automatically.

The simulator was committed separately in `29fed9c` before optimizer code in `98c9202`.

### Brief-led video direction

The new [Video Director](docs/VIDEO_DIRECTION.md) turns a Brief Writer brief into an object-led
sequence, with automatic reference selection, deterministic timing, unique motion shots,
sparse white type and separate EN/AR editions. Start with `instabay direct-video --brief path/to/brief.json`; finished rendering requires motion footage, while `--render --animatic`
explicitly produces a photo edit. Preview generation never stores a publishing approval.
