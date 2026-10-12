# Instagram adapters: Phase 5

`GraphPublisher` implements the existing publisher protocol. It accepts one stored, approved
post, validates the final EN + AR caption and media manifest, verifies public bytes, checks
quota, creates containers, polls processing and stores a live receipt. `GraphInsights` ingests
parent-media lifetime counts into SQLite. Tests use synthetic contracts; **no live post or
real insights fetch has been verified**. The offline week/cycle remains separate.

## Prepare a live post

# HUMAN: create your Meta app/account/token, verify permissions, and edit/freeze your brand.
Use a non-demo run. Attach `MediaManifest` to `Post` **before** checks and human approval.
Its approved fields include public immutable HTTPS URLs, SHA-256, size, dimensions, MIME,
sRGB image metadata, human verifier and reference-only status. Upload media to your own
public host and add that host to a copy of `config/instagram.example.yaml`. No token belongs
in that YAML. Historical Grand Resort reference photos are blocked by default.

A photo needs one JPEG; a carousel supports 2-10 JPEG images. Set `media_status=ready`.
A reel needs a verified MP4/MOV, stored inline render recipe and exact canonical recipe hash,
and `media_status=rendered`. Generated footage needs `ai_disclosure=true`; the final caption
includes both disclosure lines. Stub renders are blocked. A recipe is not proof of truthful
facilities: the human checks visual fidelity and usage rights before approval.

The native verifier checks HTTP 200, MIME, byte count and content SHA-256, with bounded
streaming and redirects disabled. Verification runs before creation and again immediately
before publishing, so changed public bytes stop the operation. Codec, color-space, dimensions, timing and fast-start
metadata are **human verified** in this phase; automatic render/probe QA comes in Phase 7.
A media edit changes the content hash and requires new checks and approval. Old judge scores
cannot be relabeled as fresh checks. The production drafting/decision workflow is pending;
these adapters consume already prepared non-demo database posts through the repository API.

## Native commands

# HUMAN: invoke these only after the preceding preparation; this phase did not run them.
Keep `INSTABAY_MODE=dry_run` normally. For an intentional live operation, set it to `live`
in the ignored `.env`, with `INSTAGRAM_USER_ID` and `INSTAGRAM_ACCESS_TOKEN` populated.
Both native commands additionally require `--confirm-live`. A missing flag, credential,
non-demo run, frozen brand, approval or ready media blocks publishing.

```sh
uv run --env-file .env --offline --no-sync instabay graph-publish \
  --db outputs/live.sqlite3 --post-id YOUR_POST_ID \
  --config config/instagram.example.yaml --confirm-live
uv run --env-file .env --offline --no-sync instabay graph-insights \
  --db outputs/live.sqlite3 --post-id YOUR_POST_ID \
  --config config/instagram.example.yaml --confirm-live
```

Bearer tokens stay in headers inside the native transport, never request parameters,
serialized credentials, journals, fixtures, errors or receipts. Native requests recheck
mode and environment credentials on every call. CLI failures print a safe error category, numeric API codes and an available Retry-After hint.
Use stored job state and the categories below to investigate; do not enable header/body logging.

## Retry semantics

Every HTTP operation rechecks the latest APPROVED/EDITED decision against the exact post hash
inside a SQLite write transaction. A rejection stops the next operation. The transaction
prevents concurrent approval changes during the current HTTP request. A request already
accepted by Meta cannot be recalled by a later rejection.

Creation/publish intent commits **before** the POST. Accepted child/container/media IDs commit
before the next operation. A restart with a local receipt returns it without another request.
Concurrent adapters use the same journal and cannot duplicate creation or publishing.
The job and receipt bind account, login path, API version and a hash of the approved publish
intent (including manifest); carousel child IDs are stored separately as they are accepted.

| Category | Behavior |
|---|---|
| `GraphPendingError` | At most six processing checks with five 60-second sleeps, then stop. Retry resumes the same container. A separate ready-status check precedes publishing. |
| `GraphRateLimitError` | Store known rejection, preserve accepted IDs, stop. Respect `retry_after_s` when present and retry explicitly; there is no automatic POST backoff. |
| `GraphContainerError` | ERROR/EXPIRED is terminal. No automatic recreation or receipt. |
| `GraphTransportError` / malformed POST response | Outcome may be unknown. Keep committed creating/publishing intent; never blindly repeat the POST. |
| `GraphReconciliationRequired` | # HUMAN: establish what Meta accepted before any further mutation. A PUBLISHED container does not reveal the media ID. Never substitute a container ID or infer identity from a matching caption. |
| `UnapprovedPublishError` | Latest approval absent, rejected or stale. Stop before HTTP. |
| `LiveConfigurationError` / `MediaValidationError` | Correct preparation/configuration before retrying. A preflight-only job can be edited; accepted or uncertain container operations freeze the snapshot. |

There is deliberately no automatic reconciliation or journal deletion command. If Meta
accepted a POST but its response was lost, preserve the journal and verify the exact account,
container and media association externally. A reviewed recovery migration/runbook belongs to
the go-live phase. Offline tests prove safe refusal and local retry semantics, not remote
exactly-once behavior under an ambiguous response.

## Insights and learning

Only the stored published parent media ID is queried. Reels must report VIDEO with
`media_product_type=REELS`; carousel children are never queried. Metrics use `views`, `reach`,
`likes`, `comments`, `saved`, `shares` and reel `ig_reels_avg_watch_time`. Empty/partial batches
are stored with missing names; missing values are not replaced by zero. Zero-reach counts
remain available, but engagement rate is undefined. Real interaction types can overlap;
the raw engagement ratio may exceed 1. Average watch time stays in milliseconds and is not
misreported as watch-through. Repeated identical timestamp observations are idempotent;
conflicting observations fail atomically.

Real batches have a distinct typed boundary from the simulator's exclusive bounded counts.
This phase does **not** update live bandit beliefs. Calibrated content-bound fidelity and an
explicit real reward definition are required before live learning is wired in Phase 6.

## Sources and verification limits

The [official Meta Postman workspace](https://www.postman.com/meta/instagram/overview) and
[container status example](https://www.postman.com/meta/instagram/request/munmruq/get-ig-container-status)
support the create/status/publish flow and distinction between container and media IDs.
The main Meta documentation pages returned access errors during this phase, so supported
versions, permissions, quotas, insights support and media limits remain HUMAN verification
items, not a claim that the current API was fully checked.

SPEC pins v25.0 and chooses a conservative cap of 50 API posts per rolling window. Both are
configurable; quota checks also honor a lower returned quota total. The official
[reel request example](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-1ff01566-3509-48bd-a0f4-8571a91ccfdf)
shows a 1 GB upload limit, while SPEC says 300 MB. This adapter retains the conservative,
configurable 300 MB cap. Carousel videos and resumable upload are not implemented.
