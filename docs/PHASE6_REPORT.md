# Phase 6 report

## 1. Built

- `decisions/engine.py`: typed Choice/Score/Noul questions/answers, exact-input fake and shared
  protocol. Fake boundary was committed before native implementations (`14e0216`).
- `jev_http.py` / `laya_local.py`: opt-in bearer-header HTTP, explicitly pinned hosted model
  identity, guarded lazy CUDA Router with local checkpoints and disabled optional fallback selection.
- `calibration.py`: independent gold/prediction boundaries, bilingual group splits, validation-only
  confidence fitting, held-out precision intervals/ECE/escalation, scoped thresholds and human kappa.
  `decision_commands.py` adds offline `calibrate-decisions`; no default gold labels are fabricated.
- `questions.py`, `cascade.py`: Markdown EN/AR atomic questions, deterministic rules first,
  selective escalation context, reproducible 10% audits, one refinement and content-bound evidence.
- `fidelity.py` / `guardrail.py`: calibrated EN/AR D1 consensus and D3 review/block/allow gate.
- `WeekRunner` accepts optional engine/profile configuration. SQLite retains raw/calibrated
  decision records and trace provenance; score-free System-1 reviews survive restarts and still
  require human approval. Nullable migration preserves legacy judge reviews. CLI preview avoids
  invented rubric scores; benchmark helpers explicitly require judge evidence.
- [Usage/HUMAN requirements](DECISIONS.md), [ADR 0006](adr/0006-calibrated-cascade-and-evidence.md),
  dedicated escalation prompts and synthetic fixture/native/graph tests.

## 2. Gate evidence

| Check | Result |
|---|---|
| `make setup lint test` | Locked setup succeeds; **215 offline tests**, Ruff clean; strict mypy clean in **62 files**. |
| New Phase 6 coverage | **40 checks**: typed fake, malformed primitives, native opt-in/auth/import failures, grouped splits, validation-only fitting, trust scope, thresholds, audits, selective escalation, adverse decisions, one revision, D1 disagreement, D3 uncertainty and full graph restart. |
| Graph gate | Active calibrated fake reaches approval interrupt, cannot resume without stored decisions, saves 70 atomic records, resumes across processes and exports only synthetic-approved posts. |
| Container | Real `instabay:phase6` image, UID 10001, network disabled, read-only test helpers: 70 records, 7 score-free System-1 reviews, approval refusal, restart and 7 synthetic dry-run exports. No torch/Laya imports or native inference. |
| Separate default demo | 7 drafts, 0 approvals/publications/metrics/beliefs/decision rows; judge-only default; no outbox. |
| Repository hooks | Ruff, formatting, strict typing and secret scanning pass. No additional scanner exclusions. |
| Protected files | SPEC, simulator, planner/optimizer, reference photos and Phase 4 benchmark results unchanged. |

Native engine checks use httpx.MockTransport and optional-module doubles. All tests block sockets.
The existing offline bench/Graph publisher suites continue passing. GitHub CI is available on the
Phase 6 PR and its final result is reported at delivery. Phase 6 commits/PR use mazenDDr only.
The Tailscale/SSH preflight reached idle gpu-box (860/16311 MiB, 0%); no job, model download,
paid call, live post or real approval was performed.

## 3. Deviations / decisions

No `0000-spikes.md` or real audited gold set exists. Default remains judge-only. Synthetic
calibration can exercise fake demo paths only and cannot authorize native fast paths. Actual
300-item bilingual gold, 60 human audits, model accuracy, quality agreement, latency/cost savings
and any Arabic fine-tune remain HUMAN work, with no fabricated results.

ADR 0006 scopes the dependency-free fitter to reported-confidence correctness logits rather than
assuming Laya's native class-logit calibration API transfers to Jev. Group splits preserve EN/AR
counterparts and duplicate-content groups. Held-out test can disable a frozen validation threshold,
never retune it. Precision is observed with an interval, not a guaranteed future rate.

Only uncertain/adverse IDs enter escalation context; the existing full three-sample rubric
still returns the quality verdict. Dedicated AR escalation instructions are Arabic. A System-1
pass stores no fabricated rubric samples. Human approval remains mandatory on every route.
D1 does not infer actual publication time, and live Graph reward/learning remains blocked.
D4 training/queue ranking and D5 live comment triage depend on real human logs/go-live ingestion;
queue ordering stays FIFO. Optional Laya package and hosted wire/model checks remain unverified
beyond primary-source inspection and synthetic contracts.

## 4. HUMAN items

- # HUMAN: review/merge the Phase 6 PR.
- # HUMAN: run/record Phase 0 Laya/GPU spikes and verify a compatible pinned runtime without
  replacing gpu-box's prepared CUDA torch build. Confirm local checkpoint completeness.
- # HUMAN: record real D1/D2 predictions, obtain independent judge labels (different model family),
  audit at least 60 of 300 bilingual items with >=40% Arabic and inspect precision intervals/kappa.
- # HUMAN: fit/check the actual profile, measure runtime/costs and validate held-out behavior
  before enabling a native fast path. Fine-tune Arabic only if real results justify it; recalibrate.
- # HUMAN: credentials, brand freeze, media verification and intentional live API validation
  remain separate from calibration and never become automatically approved.

## 5. Proposed next step

After review/merge and explicit continuation: Phase 7 Video Studio—shot lists, recipe/hash cache,
stub render path, post-processing/QA and guarded gpu-worker/backend code. Read SPEC §7 and any
Phase 0 spike ADR first. Phase 7 has not begun.
