# 0005: Durable Graph intent, conservative media and separate real insights

Status: accepted for Phase 5. A local idempotency key cannot prove remote exactly-once posting
when a mutating response is lost. Persist intent before each POST and accepted IDs before the
next operation; guard each operation with the latest exact approval under a SQLite write lock.
Known rejection permits an explicit retry, while timeouts, malformed IDs, 5xx and crashes stop
for human reconciliation. Never infer a media ID from a PUBLISHED container. Bind approved
media bytes and recipe into Post, with nullable additive migrations preserving existing hashes.
Real insights use a separate boundary because counts may overlap and metrics may be absent;
store partial/empty batches and raw counts without simulator assumptions or live bandit updates.
Primary Meta pages were unavailable, so configurable SPEC version/quota facts stay [verify].
Retain the conservative 300 MB video cap despite the official Postman example's 1 GB figure.
Photo/image-carousel/reel URL upload is the scoped path; automated media probe QA, production
agent wiring, calibrated live learning and a reviewed ambiguous-operation recovery runbook
remain later-phase work. See [adapter behavior, sources and HUMAN steps](../INSTAGRAM.md).
