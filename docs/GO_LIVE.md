# Go-live runbook

The offline prototype, real local generation and private recording/replay are implemented.
The [production generation workflow](PRODUCTION_GENERATION.md) creates non-demo mixed content
under a stored human-frozen brand and stops at approval. Instagram is deliberately pending.
No live account, public media host, calibrated native evidence or live reward/learning is
verified. Keep `INSTABAY_MODE=dry_run` until the separate Instagram preparation is complete.
[Current backlog](BACKLOG.md) distinguishes implemented generation from remaining launch work.

## 1. Reproduce the offline system

```sh
# HUMAN: use the requested GitHub identity; do not paste tokens into commands or logs.
gh api user --jq .login  # expected: mazenDDr
gh repo clone mazenDDr/instabay-agent
cd instabay-agent
make verify-clone
```

`verify-clone` builds the validation image from this checkout, prepares locked dependencies,
then runs `make setup demo test lint` without network access. The fixture demo must stop with
seven drafts, zero approvals/publications/metrics/beliefs and no outbox. The tests may create
clearly marked synthetic approvals in disposable state; they do not approve the demo queue.
The normal runtime image is separate and does not include development tools or Git history.

For interactive dry-run review, use one consistent database/checkpoint/outbox set:

```sh
make setup
make demo
uv run --offline --no-sync instabay approve --run-id 2026-w42 --actor YOUR_NAME
uv run --offline --no-sync instabay resume --run-id 2026-w42
```

These commands export intent JSON only. Rejection skips a post. Changing copy/media invalidates
prior approval. To see actual fixture media, use `demo --render-reels` or the standalone recipe
in [VIDEO.md](VIDEO.md); those previews remain reference-only and cannot go live.

## 2. Close the engineering prerequisites

Use `instabay generate` with the pinned private native client or an explicit recorded replay.
`make record ARGS="..."` now records private cassettes, and native generation captures them
automatically. [PRODUCTION_GENERATION.md](PRODUCTION_GENERATION.md) describes source preparation,
photo animation, frozen-brand selection, budgets, retry, resume and review. The default
FakeLLM demo remains an offline demo and is not relabeled as real inference.

Keep live observations out of the optimizer until a reviewed bounded reward and calibrated
executed-arm evidence are wired. Real interaction types overlap; the simulator's exclusive
count assumptions do not transfer automatically. Approval-log ranking, comment ingestion/triage
and prompt tuning are separate backlog tasks. Do not imply they already operate in production.

## 3. Human data and brand

# HUMAN: edit the draft, verify facilities/offers/cadence and explicitly freeze the constitution.
No source-resort image establishes an Insta Bay facility, room or current offer.

```sh
uv run --offline --no-sync instabay brand-draft --db outputs/live.sqlite3
# HUMAN: save your reviewed constitution to config/brand.yaml.
uv run --offline --no-sync instabay brand-freeze --brand config/brand.yaml \
  --db outputs/live.sqlite3 --actor YOUR_NAME
```

The brand draft is still a fixture proposal. Preserve its source records and freeze actor/hash;
a changed constitution requires new content checks and approval. Provide real benchmark ratings
and independently recorded native/MT comparisons before reporting brand/Arabic quality.
For native decisions, obtain 300 independent bilingual items (>=40% Arabic) with at least 60
human audits and inspect held-out precision intervals/kappa. Follow [DECISIONS.md](DECISIONS.md).
Leave absent/failed cells judge-only; never use synthetic profiles to authorize native inference.

## 4. GPU and media preparation

# HUMAN: run Phase 0 spikes on gpu-box through Tailscale and record `docs/adr/0000-spikes.md`.
Use the prepared `main` environment; verify compatibility without replacing its CUDA torch
build. Prepare pinned local model/config hashes and record actual package/GPU/driver/image
identity. The measured Wan5B photo-to-video preset and NF4 Qwen8B fit the prepared 16 GB GPU, one model at
a time. Those trials do not establish FLF support, cross-machine determinism or calibrated
semantic quality. Preserve their recipe/runtime evidence.

Approve photo crops, rights, guests/signs and semantic fidelity before native motion. Generated
stills may depict mood, not invented amenities. Generated footage requires EN/AR caption
disclosure and `ai_disclosure=true`. Check the complete recipe, MP4, contact sheet and actual
encoding, DINO/vision/continuity/brand evidence. Missing visual QA must remain visible for review.
Do not relabel a synthetic sample as resort footage or a CPU frame test as GPU determinism.

Before launching the worker, restrict Tailscale ACLs, supply a token from `.env`, bind only the
private address, use a pinned image/read-only input volume and one worker. Validate health,
unauthorized refusal, one approved recipe and restart/idempotency behavior. A failed native or
crashed running claim needs reconciliation; do not delete its queue row or blindly re-submit it.
The scheduled GPU golden workflow remains disabled until explicitly configured by a human.
Full launch instructions and known backend limits are in [VIDEO.md](VIDEO.md).

## 5. Meta/account verification

# HUMAN: create the Meta app/account/tokens and confirm the current supported login path,
version, permissions, account eligibility, quota, reel/carousel limits and insights availability
against [Meta publishing docs](https://developers.facebook.com/docs/instagram-platform/content-publishing)
and [insights docs](https://developers.facebook.com/docs/instagram-platform/insights).
Those pages were inaccessible during this phase's verification. Example values are not a current
platform guarantee. Store credentials only in git-ignored `.env` or CI secrets.

Copy `config/instagram.example.yaml` to a reviewed account configuration with your immutable
public media host allowlist. Keep tokens out of YAML. Use `generate` to prepare a separate non-demo run under the frozen brand. Review the resulting
photos, carousels, reels and exact post snapshots before the distinct publishing step.

Attach verified `MediaManifest` bytes/metadata/public HTTPS URLs to the post before checks and
approval. Feed assets need verified source/rights/specs; reels also need the exact stored recipe,
render hash, real media QA and generated-footage disclosure. Mark reference-only media accordingly;
never clear the flag just to pass a guard. Stub reels are blocked by the native publisher.
A local preview attachment is not a public live media manifest. No media host is provisioned here.

## 6. Intentional first publish and insights

# HUMAN: inspect the final EN/AR captions, media and flags, then store your explicit decision in
that same live database. Verify its hash is current. Set `INSTABAY_MODE=live` only for the intended
native commands and restore `dry_run` afterward. Both commands also require `--confirm-live`.

```sh
uv run --env-file .env --offline --no-sync instabay graph-publish \
  --db outputs/live.sqlite3 --post-id YOUR_APPROVED_POST_ID \
  --config config/instagram.live.yaml --confirm-live
uv run --env-file .env --offline --no-sync instabay graph-insights \
  --db outputs/live.sqlite3 --post-id YOUR_APPROVED_POST_ID \
  --config config/instagram.live.yaml --confirm-live
```

Record the exact account/container/media association and verify the actual Instagram result.
A command failure may mean a remote POST succeeded while its response was lost. Preserve the
journal, stop mutations, establish the accepted IDs externally and review recovery before doing
anything else. Never substitute a container ID for a media ID. There is no automatic journal
recovery/deletion command. [INSTAGRAM.md](INSTAGRAM.md) describes safe retry categories.

Ingest only the published parent media's real observations. Preserve empty/missing values and
raw overlapping counts; average watch time is not watch-through. Inspect the stored batch
provenance/account/version and observe receipts across retries. This currently stores real
metrics without learning. No simulator observations should enter the live account scope.

## 7. Operations and evidence

Back up the business database, checkpoints, immutable render recipes/results and Graph journal
together when jobs are quiescent. Restore to separate paths and inspect matching snapshots;
never overwrite active state to escape an approval or uncertain-job guard. Keep `.env`, raw human
ratings and provider recordings private. Restrict database/write access to trusted operators.

A safe stop keeps the default mode at `dry_run`, stops new jobs/requests and preserves receipts.
Existing remote posts are not recalled by later rejection. Log safe categories and exact IDs,
not credential headers, private provider bodies or arbitrary exceptions. Rotate credentials
through the provider/account process after exposure; tests never need real credentials.

Report only measured scope: real source/model revisions, independent labels, held-out uncertainty,
wall time/cost, acceptance/rejection/edit rates and native video QA. Add evidence before upgrading
any pending capability to verified. The remaining product choices, paid work, account setup,
real approvals and deployment are human decisions beyond this offline documentation phase.
