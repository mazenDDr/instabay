# Production generation — photos to an approval queue

The accepted approach is real photographs with restrained generated movement, assembled into
scenic reels alongside single-photo and carousel posts. The non-demo generator uses a stored,
human-frozen brand and curated source facts, independently frames EN/AR copy, records actual
model responses, renders media and stops at approval. It does not publish to Instagram or feed
live metrics into the optimizer. Demo acceptance is direction feedback, not stored post approval.

## Inputs and one-time preparation

Put the source photographs under the project root. Use the schemas exemplified by
`config/reethi-faru-scenes.yaml` and `config/reethi-faru-evidence.yaml`: stable image IDs,
checksums, source/rights/face review, observed features, localized factual clauses and pillar
guidance. Never label third-party reference media as owned/current facilities. The named example
is historical reference material; it stays reference-only. Manual first/last video frames are
not required. Conditioning is prepared internally and retained byte-for-byte with source/crop
hashes, including when another FFmpeg build would encode the same crop differently.

Review your brand's cadence. For the demonstrated mixed week, set `min_photos: 3`,
`min_carousels: 2`, `min_reels: 2` and `posts_per_week: 7` before freezing. The existing frozen
configuration is never edited automatically.

```sh
# HUMAN: verify/edit the constitution; this command stores your explicit freeze in this DB.
uv run instabay brand-freeze --brand config/brand.yaml \
  --db outputs/production/posts.sqlite --actor YOUR_NAME
```

## 1. Prepare physical movement on gpu-box

Use the existing `main` conda environment and pinned Wan weights. Deploy the worker modules
from the Mac without deleting remote caches or replacing Torch:

```sh
rsync -az --exclude=__pycache__ gpu_worker/ gpu-box:/home/mazen/instabay-native/gpu_worker/
INSTABAY_GPU_ENABLED=1 uv run instabay animate-photos \
  --scenes config/YOUR-approved-scenes.yaml --output outputs/photo-motion --confirm-gpu
```

The source catalog must use `edit_style: scenic` and real approved photographs. New motion uses
the measured 576×1024, 61-frame/12fps, 40-step, CFG5, shift3 preset. Default GPU budget is 45 minutes,
with an initial estimate of 7 minutes per uncached photograph. Each request runs in an identified
remote tmux job. Its recipe/receipt precede inference. Repeating the command recovers completed
clips and the partial catalog; it does not blindly resubmit a started or failed recipe.
Uncertain/failed jobs need receipt reconciliation. GPU contention stops a new launch.

This stage writes `outputs/photo-motion/catalog.json` with native recipe/clip hashes and exact
conditioning files. Existing verified clips can be supplied instead. Caption generation and
photo animation are separate stages so the 16 GB GPU holds only one large model at a time.
Generated motion remains reference-only pending the later media-certification/Instagram work;
the generator never clears that protection merely because the visual direction was accepted.

## 2. Start the private caption service

```sh
ssh gpu-box 'cd /home/mazen/instabay-native && INSTABAY_LLM_ENABLED=1 \
  /home/mazen/miniconda3/envs/main/bin/python -m uvicorn \
  gpu_worker.caption_llm_server:app --host 127.0.0.1 --port 8765'
# A separate terminal; dedicated keepalive tunnel, rather than an idle ControlPersist tunnel.
ssh -o ControlMaster=no -o ControlPath=none -o ServerAliveInterval=30 \
  -N -L127.0.0.1:18765:127.0.0.1:8765 gpu-box
```

The worker verifies pinned local Qwen3-8B weights and loads NF4 with disabled thinking. It never
downloads weights implicitly. Warm the model through the explicit private `/warm` endpoint
before a bounded generation request:

```sh
curl --fail --max-time 600 -X POST http://127.0.0.1:18765/warm
```

Stop the caption process before another photo-motion job.
Model ID: `Qwen/Qwen3-8B:nf4@b968826d9c46dd6066d109eabc6255188de91218`.

## 3. Generate a real non-demo week

```sh
INSTABAY_LLM_ENABLED=1 uv run instabay generate \
  --brand config/brand.yaml --evidence config/YOUR-evidence.yaml \
  --scenes outputs/photo-motion/catalog.json \
  --model 'Qwen/Qwen3-8B:nf4@b968826d9c46dd6066d109eabc6255188de91218' \
  --run-id YOUR-week-id --week-start 2026-10-19 \
  --output outputs/production --confirm-generation
```

Keep `INSTABAY_MODE=dry_run`. Default limits are 70 provider attempts, 200000 tokens and $1 API fees;
local GPU/electricity are not included in the API-fee figure. Actual failed attempts count, and
usage is restored from the ledger on resume. Explicit ceilings may change without changing
content inputs. Brand, model, prompt hashes, evidence, source catalog, run ID and date are bound
in the immutable run manifest; changed content inputs require a new run/output directory.

Repeat the same command after an interruption. The database/checkpoints/cache retain completed
work. `--draft-only` explicitly creates concepts without finished reels; it is not a silent
fallback from missing physical footage. A process lock prevents two writers for the same run.

Outputs include actual feed images/reels, source evidence, recipe hashes, a private
`cassette.json`, `campaign.json`, and `review/index.html`. Reviews keep factual/spec failures
and pending semantic checks visible; no uncalibrated beauty score is fabricated. The gallery
is reviewable copy, and approval remains bound to the database post's exact content hash.

## 4. Record or replay without credentials/network

Real runs automatically record exact requests and raw completions, including schema-invalid
responses and sanitized provider failures. Capture files are owner-readable, single-writer,
atomic and integrity-checked. Credential fields/known environment secret values are refused.
Captures stay under ignored `outputs/` or outside the repository, never public fixture folders.

To intentionally re-record audited request files:

```sh
INSTABAY_LLM_ENABLED=1 make record ARGS="--requests outputs/YOUR-audit-calls \
  --model Qwen/Qwen3-8B:nf4@b968826d9c46dd6066d109eabc6255188de91218 \
  --output outputs/cassettes/week.json --confirm-generation"
```

Recording resumes completed exact requests, binds the request set and enforces call/token/fee
ceilings. It saves raw responses; the generating service still performs schema validation and
its one retry. Recording alone is not a content-quality verdict.

For offline replay into separate state, first store the same explicitly frozen brand there,
then run the same `generate` arguments with a new output directory and
`--replay outputs/production/cassette.json`, without `--confirm-generation`. Keep the original
run ID/date/model/evidence. Exact request/schema/prompt matching is required; missing entries
raise rather than contacting a provider or falling back to FakeLLM. The report explicitly
labels recorded replay, not new inference. A second complete run uses its checkpoint/cache.

## Waiting for Instagram

No credentials, upload host, live publishing trial, real reward/learning, visual calibration
or media certification is added here. Historical reference samples remain blocked from live
publishing. Brand freezing and individual post decisions remain explicit human actions. The
Instagram phase can consume the resulting reviewed non-demo posts after its own preparation.

## Integration and generation gate report

1. Built: main now includes the previously stacked content/video changes. `generate` consumes
   a stored frozen brand, `animate-photos` captures/resumes native motion, and `record`/replay
   retain exact private provider evidence. Conditioning bytes survive cross-platform assembly.
2. Gate evidence: `make check` passed 327 offline tests plus Ruff/strict mypy; all local hooks
   passed. A real Wan photo-motion job completed, native Qwen produced 3 photos / 2 carousels /
   2 reels, and exact EN/AR copy replay passed on Mac and in Docker with `--network none`.
   Chrome 154 verified both 15-second reels, carousel navigation, Arabic and mobile layout.
   See the [sanitized verification report](production-generation-verification.json).
3. Deviations: explicit owner authorization allowed real network/GPU work and excluded remote
   CI as a gate. CI configuration/billing were unchanged.
   [ADR 0012](adr/0012-non-demo-generation-and-captures.md) records the architecture.
4. `# HUMAN:` the verification used historical reference media and a disposable synthetic
   frozen-brand fixture, not an owner/customer freeze or any post approval. Before a real
   account campaign, freeze its verified constitution and review exact posts/current media.
5. Next step: wait for the owner to start Instagram preparation. Hosting, Meta credentials,
   media qualification, intentional publishing and real learning remain outside this delivery.

All three validated runs are non-demo and stop at `approval_pending`, with zero approval and
publication rows. Raw captures and mutable databases remain in ignored local outputs. The
caption service/tunnel were stopped; gpu-box returned to 496 MiB and 0% GPU utilization.
