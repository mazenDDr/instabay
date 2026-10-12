# Phase 3: frozen audience, synthetic fidelity and scoped learning

The simulator was committed as `29fed9c` before optimizer code. Keep its constants and
frozen seed fixture unchanged; Phase 4 adds comparisons and intervals without tuning the
world to Thompson sampling. Use independent Beta(1,1) priors and the specified fractional
20-observation update. Sample each factor level once per week and feed those scores to the
existing integer constrained planner, including its explicit exploration slot. The analyst
computes descriptive statistics in code; an LLM explanation adds no value to this phase.

Real D1 engines and calibration belong to Phase 6. Phase 3 therefore uses explicitly
synthetic fixture D1 labels for exact canned brief/copy content. A compact JSON catalog has
explicit template+slot keys and canned arm variants; unknown keys and cases still fail.
The fixture authoring script enumerates all arms independently of policy performance, and
never runs during replay. Edited or missing labeled content remains unverified and does not
update beliefs; known executed-arm mismatches are logged as leakage and also skipped.
Judge rubric scores are never treated as fidelity evidence. These labels validate software
wiring, not a real model's accuracy. # HUMAN: provide ratings/calibration data in Phase 6.

Store insights in long format plus an immutable content-bound learning receipt. Metrics,
receipt and four posterior changes commit in one SQLite write transaction, so partial
failures and concurrent retries cannot double-learn. Scope posteriors by brand and audience
seed/configuration. Migrate the Phase 2 posterior table transactionally, preserving any
prototype rows in an isolated legacy scope. Cycle inputs (including fixture and brand-input
hashes) are fixed at first invocation; every new week waits for stored human decisions.
Only disposable automated tests insert synthetic approval decisions.

Unverified edited content still receives clearly synthetic metrics using the planned arm as
an explicit assumption, with `arm_assumed=true`; it cannot teach the optimizer. The 48-hour
observation timestamp is logical simulation time, not a claim about real Meta availability.
The exclusive synthetic counts produce rewards in [0,1]; a real Graph adapter must define
its normalization for repeated interactions in Phase 5. Benchmarks, confidence intervals,
live publishing, calibrated engines and rendering remain deferred to their phase gates.

Secret scanning initially flagged the public SHA-256 fixture signatures. Reproducing the
entire catalog from its offline authoring script verifies those values. The hook excludes
only the exact JSON line shape of a 64-character hexadecimal `content_signature`; the
remaining catalog text and all other credential detection stay enabled.
