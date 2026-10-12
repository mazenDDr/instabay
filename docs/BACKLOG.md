# Remaining work after the offline build

The eight build-phase gates cover an offline prototype and guarded adapter code. They do not
establish an end-to-end production campaign. Default demos/tests need no keys, network or GPU.
[GO_LIVE.md](GO_LIVE.md) gives the order of preparation; this backlog records missing work rather
than assigning finished phases again.

## Engineering prerequisites

| Work | Current state | Completion evidence |
|---|---|---|
| Production LLM adapter and non-demo drafting/check workflow | `LLMClient` protocol and fixture service exist; no real provider client or native drafting command. | Sanitized usage/provenance/budget/retry contracts plus a human-run real capture. |
| Cassette recording | `make record` is an explicit refusal/placeholder. | Human-invoked recorder with pinned keys/templates/models, safe private storage and offline replay. |
| Live reward/learning integration | Native insights are stored; bandit updates are blocked. | Reviewed bounded reward for overlapping counts, calibrated executed-arm fidelity, isolated account scope and idempotent receipts. |
| Native semantic/temporal/brand video QA | Interface and missing-evidence flags exist; DINO/Qwen-VL adapter/results absent. | Pinned real visual measurements, threshold validation and independent human audits. |
| Native deployment/recovery | Worker/Graph journals hold uncertainty; no deployed service or automatic reconciliation tool. | Human-reviewed private setup and recovery procedure based on exact externally confirmed IDs. |

## Human prerequisites

- # HUMAN: edit/freeze verified brand facts; create provider/Meta keys and choose permitted accounts.
- # HUMAN: approve real resort photo crops/rights/faces/fidelity; keep source identity and credit.
- # HUMAN: record Phase 0 GPU/Laya/FLF/runtime spikes, verify read-only weights and memory fit.
- # HUMAN: collect real bilingual calibration labels/benchmark ratings and independent native/MT pairs.
- # HUMAN: verify current Meta support/configuration, perform intentional first publishing/insights,
  and restrict Tailscale worker/runner access before deployment.

## Additional specification items / extensions

GEPA prompt optimization, learned approval ranking (D4), live comment triage/ingestion (D5),
Qwen image generation/editing, RIFE interpolation/upscalers, C2PA credentials and Veo/LTX blind
comparisons remain unimplemented. Comfy output subfolders/resumable Graph upload/carousel video
and broader Wan/LoRA variants are unsupported. Prioritize them only after the prerequisites and
real measurements justify the scope; no new work starts automatically after Phase 8.
