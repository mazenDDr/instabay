# Phase 5 report

## 1. Built

- `adapters/graph_transport.py` supplies the strict synthetic transport protocol/fake first;
  `graph_http.py` adds native bearer-header HTTP and public byte verification.
- `graph_publisher.py` and `graph_store.py` guard every operation with the latest exact
  approval, persist intent/IDs across restarts, support photo/image-carousel/reel URL upload,
  check quota, bound polling and refuse ambiguous mutation retries.
- Core models bind media manifests and render recipes into approval. Nullable SQLite
  migrations preserve legacy hashes, approval rows and dry-run receipts. Accepted/uncertain
  operations freeze edits; a preflight-only failed operation can be corrected.
- `graph_insights.py` stores parent-media raw metrics and complete/partial/empty observation
  provenance. It does not invent zero values, watch-through or live bandit updates.
- `graph_commands.py` adds HUMAN-only `graph-publish` / `graph-insights`; `approval.py` previews
  approved media URLs, bytes and recipe hashes. Native errors expose safe numeric retry hints.
- `config/instagram.example.yaml`, synthetic fixtures, contract/guard/native HTTP tests,
  [adapter usage](INSTAGRAM.md) and [ADR 0005](adr/0005-graph-journal-and-real-insights.md).

## 2. Gate evidence

| Check | Result |
|---|---|
| `make setup test lint`, followed by final `make lint test` | Locked setup succeeds; **175 offline tests**, Ruff clean; strict mypy clean in **53 files**. |
| Phase 5 contracts | **32 checks**: FINISHED, ERROR, EXPIRED, polling, rate/quota rejection, known receipt retry, timeout/5xx/malformed-ID refusal, three formats, bytes changed during processing, real metric shapes and malformed insight rejection. |
| Phase 5 unit/guard checks | **40 checks**: no I/O before approval, live/brand/media refusal, metadata/hash checks, native header handling, secret-safe errors, active edits, migrations, concurrent requests and CLI refusal/retry hints. |
| Repository hooks | Ruff, format, strict typing and offline secret scan pass. A single invalid synthetic Basic Auth URL has an explicit narrow allowlist annotation; scanning stays enabled. |
| `docker build -t instabay:phase5 .` and network-disabled acceptance | Real image runs as UID 10001; three formats, no-approval refusal, idempotent receipts, empty/reel insights and ambiguous-response refusal pass with synthetic fixtures mounted read-only. No real keys or calls. |
| Fresh explicit demo with separate database/checkpoint/outbox paths | Seven drafts; zero approvals, publications, metrics, beliefs, Graph jobs and insight batches. Stops at approval; no outbox created. |
| Protected-source comparison against merged Phase 4 | SPEC, simulator, planner, optimizer, original photo bytes and benchmark results unchanged. |

The approval safety regression was committed as `803fccd` **before** the publisher source
existed; it initially failed on the missing module and now passes. Tests disable sockets.
Build/setup dependency downloads are separate from offline tests. GitHub CI is available on
the Phase 5 PR; delivery reports its final status separately. All Phase 5 commits use mazenDDr
as author and committer. No approval was inserted into the normal human review queue.

## 3. Deviations / decisions

ADR 0005 records conservative configurable SPEC caps, source-access limitations and safe
refusal after ambiguous responses. Official Meta Postman examples were readable, but primary
Meta documentation pages returned access errors. Versions/scopes/quotas/specs therefore remain
HUMAN verification items. Keep the 300 MB SPEC cap despite a 1 GB official example.

Real insights have a distinct protocol/model from synthetic bounded snapshots because
interaction counts overlap, zero reach and missing values are valid. Live learning remains
blocked until a calibrated fidelity/reward path exists. Photo/image-carousel/reel URL upload
is implemented; carousel videos and resumable upload are excluded. Media metadata is human
verified, while native code verifies approved byte identity. Automated probe QA remains Phase 7.
The demo/cycle still uses fixtures; native commands consume already prepared non-demo posts.
An ambiguous operation stops rather than offering an unverified automated recovery path.

## 4. HUMAN items

- # HUMAN: merge the Phase 5 PR when reviewed.
- # HUMAN: configure the Meta app/login path, validate current API contracts/permissions/version
  and quotas, create user ID/token in ignored `.env`, and intentionally invoke live validation.
- # HUMAN: freeze the real brand, verify media rights/facilities/spec metadata, upload immutable
  bytes to an allowed public host, attach the manifest before fresh checks and approve exact content.
- # HUMAN: preserve and externally reconcile any unknown accepted operation; never delete its
  journal or substitute a container ID for a published media ID.
- # HUMAN: Phase 0 GPU/Laya spikes and real judge/benchmark labels remain pending.

## 5. Proposed next step

After merge and explicit continuation, Phase 6 adds decision-engine protocols, HTTP/local
engines, calibration and tested cascade escalation. Read SPEC §§6, 5.4, 15.6 and any
`docs/adr/0000-spikes.md` before starting. Phase 6 has not begun.
