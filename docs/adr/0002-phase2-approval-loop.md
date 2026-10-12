# ADR 0002: Exact-content approval and offline graph boundaries

Phase 2 uses a deterministic constrained planner with neutral defaults and optional finite
preference scores; there is no simulator, bandit or posterior-update code. Future tables from
§10 are declared as storage schema only. Brand, arm, run, slot, post, ordered tags, judge
samples, approvals and publication receipts are separated in SQLite. A stored approval binds
the latest decision to the canonical post content hash, and BEGIN IMMEDIATE covers the
authorization check, atomic JSON artifact write and receipt. Human edits retain timed diffs
and pass deterministic rules; their old judge samples remain tied to the pre-edit hash.
Graph resume values never create approvals. Rules run before three separately keyed fixture
judge requests; System-1 and calibrated real model families wait for their phases. A failed
draft gets at most one revision, with its initial judgment retained. EN/AR requests overlap
while ledger writes and budget reservation are synchronized, and per-run usage survives
checkpoint restarts. The fixed demo brand stays unfrozen; a human-invoked freeze command
hashes an existing edited file. Reels are concepts in Phase 2 because rendering belongs to
Phase 7. Dry-run artifacts remain reference-only intents, not live-ready Instagram payloads.
The normal demo waits for real user decisions; tests use explicitly synthetic approvals in
isolated state. The existing Phase 1 call table gets a backward-compatible nullable run ID.
