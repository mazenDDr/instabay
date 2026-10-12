# Remaining work after the offline build

The eight build-phase gates cover an offline prototype and guarded adapter code. They do not
establish an end-to-end production campaign. Default demos/tests need no keys, network or GPU.
[GO_LIVE.md](GO_LIVE.md) gives the order of preparation; this backlog records missing work rather
than assigning finished phases again.

## Engineering prerequisites

| Work | Current state | Completion evidence |
|---|---|---|
| Production generation | Implemented local native client, `generate`, frozen-brand selection, source-bound mixed formats and approval stop. | See [production generation](PRODUCTION_GENERATION.md); real source media and owner brand still need their own preparation. |
| Cassette recording | Implemented private atomic capture, resumable `make record`, exact offline replay and credential/integrity guards. | Native runs automatically capture raw requests/responses; no fixture/provider fallback. |
| Live reward/learning integration | Native insights are stored; bandit updates are blocked. | Reviewed bounded reward for overlapping counts, calibrated executed-arm fidelity, isolated account scope and idempotent receipts. |
| Native semantic/temporal/brand video QA | Interface and missing-evidence flags exist; DINO/Qwen-VL adapter/results absent. | Pinned real visual measurements, threshold validation and independent human audits. |
| Native operations | Photo animation uses durable private tmux jobs and pre-inference receipts; completed work resumes. Failed/uncertain jobs and Graph journals still require reconciliation. | Production service deployment, account-specific setup and uncertain Graph recovery remain pending. |

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

The owner accepted the demonstrated photo-to-video direction and requested that Instagram wait.
Production generation is implemented; this does not constitute stored post approval, calibrated
quality scores or permission to publish. Source reference protections remain active.
