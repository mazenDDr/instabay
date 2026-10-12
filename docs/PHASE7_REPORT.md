# Phase 7 report

## 1. Built

- `video/shotlist.py` and `core/recipe.py`: approved still/shot/audio boundaries, complete measured
  recipes and canonical hashes, timing/FLF constraints, pinned bytes/runtime and facility-source rules.
- `StubVideoBackend` was committed before native implementations (`97c7300`); abstract synthetic
  still and licensed Noto Naskh Arabic font are tracked. Original resort photos remain unchanged.
- `video/post.py`, `qa.py`, `studio.py`: actual Ken Burns → shaped EN/AR overlays → 1080×1920
  H.264/AAC MP4 → spec/temporal proxy checks → contact sheet, stored recipe/result/frame hashes,
  serialized rendering and checksum-verified cache. Modified cached metadata/bytes fail closed.
- Brief Writer shot-list prompt/fixtures, opt-in `render_reel` graph node, local render attachments
  in the approval hash and additive SQLite migration. Preview/QA flags survive restart; rendering
  never creates approval. Generated-footage captions retain mandatory EN/AR disclosure.
- `gpu_worker/server.py`, `video/worker.py`, `remote.py`: authenticated private service, durable
  idempotent queue, single active claim, bounded polling and verified artifact downloads.
- Lazy guarded `WanDiffusersBackend` and pinned-workflow `ComfyUIBackend` code, explicit native
  opt-in, no remote weight download and no silent unsupported-FLF fallback. Human-enabled trusted
  GPU golden workflow plus CPU uncached frame replay tests. Native adapters were not run.
- CLI `render`/`golden`, `demo --render-reels`, CPU Docker/CI ffmpeg integration,
  [usage and HUMAN limits](VIDEO.md), [ADR 0007](adr/0007-recipe-cache-and-video-evidence.md).

## 2. Gate evidence

| Check | Result |
|---|---|
| `make setup` | Locked video/worker/Arabic dependencies installed; no torch or model weights installed. |
| `make lint test` | **252 offline tests**, Ruff and strict mypy in **83 files**; **37 new Phase 7 tests**. |
| Actual stub reel | 15 s, 1080×1920, 30 fps, H.264/yuv420p, AAC/48 kHz, faststart; 450 decoded frames. |
| Cache | Restart returns the same result without another backend call; tampered MP4/result metadata refused. |
| Uncached replay | Two independent CPU renders have identical SHA-256 arrays for all 450 decoded frames. |
| Approval graph | Real render before checks; semantic QA flags and preview/recipe hashes stored; no unapproved resume. Synthetic-only temporary approvals resume across processes into seven dry-run intents. |
| Worker | Health/auth refusal/idempotent submission/status/verified download exercised with an in-process ASGI client and real stub MP4. Local Unix event-loop sockets only; TCP/Internet remain blocked. |
| Container | Network disabled, UID 10001: rendered weekly reel, 450-frame spec/cache acceptance, approval refusal, seven synthetic dry-run intents, worker health/auth/download. |
| Separate normal demo | Seven drafts, one rendered fixture reel, zero approvals/publications/metrics/posteriors; no outbox. |
| Visual review | Actual contact sheet inspected: EN/AR lines fit and the synthetic demo label is visible. |
| Protected inputs | SPEC, simulator, planner/optimizer, resort originals/approval flags and Phase 4 benchmark results unchanged. |

GitHub CI runs actual ffmpeg renders with sockets/keys/GPU disabled. Exact-head results are reported
at delivery. Sole author/committer and PR identity is mazenDDr. Read-only Tailscale/SSH preflight
reached idle gpu-box (860/16311 MiB, 0%); no job, inference, download, paid call or live post.

## 3. Deviations / ADR

There is no `0000-spikes.md`, approved photo crop or measured native runtime/model result.
The offline gate therefore uses a labeled abstract fixture, not claimed resort footage. Stills
must already exist locally; Qwen image generation/editing, RIFE/upscalers, C2PA and Veo/LTX
comparison remain spike/stretch work. FPS conversion is CPU resampling, not claimed RIFE.
Wan code refuses LoRAs rather than recording an unapplied LoRA; Comfy output subfolders are
intentionally unsupported. Human verification must confirm custom-node commits in the running
Comfy server and selected checkpoint FLF behavior. No native deployment or GPU fit is claimed.

Automatic media-spec checks and a simple luminance temporal proxy are real. Native DINO/Qwen-VL
semantic/subject/background/seam and brand evidence is absent; the QA boundary flags missing
values. No synthetic visual scores authorize native passes. CPU frame replay is measured only
on its tested runtime, while the product advertises L0 cache reproducibility. GPU L1/cross-machine
SSIM/LPIPS, real video QA pass rate, preference, speed and paid costs are unknown. Golden GPU
schedule is disabled until a human enables the trusted runner/configuration. Pending visual QA
stays in the normal human approval queue; there is no automated approval.

Secret scanning exempts only the exact JSON `sha256` metadata line shape in addition to prior
hash keys; one invalid synthetic BasicAuth test URL is annotated. No entire new file/directory
is excluded. Fresh normal demo approvals remain untouched. See ADR 0007.

## 4. HUMAN items

- # HUMAN: review/merge the Phase 7 PR.
- # HUMAN: approve real photo crops/rights/faces/fidelity and keyframe provenance; fictional Insta Bay
  must not inherit facilities from the historical Grand Resort references.
- # HUMAN: run/record Phase 0 GPU/FLF/runtime spikes, prepare the pinned read-only checkpoints and
  compatible image without replacing the prepared CUDA torch build.
- # HUMAN: restrict Tailscale ACLs, supply the private worker token, validate actual node/runtime pins
  and reconcile any interrupted/ambiguous native job before retrying.
- # HUMAN: measure independent visual QA, Arabic footage/overlay review and uncached GPU golden
  frames; enable the trusted schedule only afterward. Paid comparisons/real labels remain pending.
- # HUMAN: brand freeze, real cassettes/keys/Meta tokens and intentional live validation remain separate.

## 5. Proposed next step

After review/merge and explicit continuation: Phase 8 documentation and fresh-clone Docker gate.
Read SPEC §§12/14; finish README, architecture, research, go-live and ADR evidence without claiming
unmeasured native capabilities. Phase 8 has not begun.
