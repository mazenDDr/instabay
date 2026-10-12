# Video Studio

Phase 7 supplies a measured offline render path and optional native transport code. No diffusion
model was run. Insta Bay remains fictional. The four Grand Resort Hurghada originals remain
unchanged and unapproved for motion; they do not verify Insta Bay's facilities.

## Offline preview

Install ffmpeg/ffprobe, then `make setup`. Both binaries are required; missing tools fail the
render/test gate. CI installs ffmpeg; the CPU Docker image includes it. No keys or GPU are needed.

```sh
make render RECIPE=config/recipes/stub.shotlist.json BACKEND=stub
make golden RECIPE=config/recipes/stub.shotlist.json BACKEND=stub
instabay demo --render-reels --db outputs/video-demo.sqlite3 \
  --checkpoints outputs/video-demo-checkpoints.sqlite3 --renders renders/video-demo
```

The supplied still is an abstract synthetic gradient. Its approval is an explicit fixture
identity, and its video says “SYNTHETIC OFFLINE DEMO.” It depicts no property or facility.
`render` accepts either a complete recipe or, for stub only, a shot list. The latter captures the
current CPU tools/implementation identity before rendering. Each hash directory stores
`recipe.json`, `reel.mp4`, `contact-sheet.jpg`, `result.json`, intermediate shots and overlays.
SQLite stores the exact recipe before motion, status, decoded-frame hashes, actual time/cost and
QA. A shared process lock serializes renders. Cache hits verify recipe, inputs and artifact hashes;
a changed cache raises an error rather than silently producing different footage.

The default `make demo` remains concept-only. `--render-reels` writes logged FakeLLM shot lists,
renders before caption checks and stops at the same stored approval interrupt. Approval binds the
recipe, preview hashes and disclosure. Rendering and QA never authorize a publication. Reference
previews have no live media manifest and cannot be posted through the Graph adapter.

## Stills and shots

`ShotList` validates 15–30 seconds total, 3–5 second shots, hook/CTA endpoints, unique IDs,
bilingual overlays and exact next-shot FLF links. Every prepared keyframe has local bytes/hash,
source, scene type, approval identity, face review and attribution. Generated stills also record
prompt/seed and can depict mood only. Facility shots require real photo sources. The Brief Writer
cannot alter/invent an approval absent from its supplied still list. This is an attestation boundary;
semantic fidelity still requires human/vision review.

# HUMAN: select/crop a source photo, check guests/signs/rights and record its exact approved
identity and hash. Keep photographer credit, source/license and modification description. Do not
change the original manifest's approval flags automatically. Qwen image generation/editing is
not implemented; any generated keyframes must already exist locally with human approval and
complete provenance. Synthetic fixture approvals cannot authorize native motion.

## Post and QA

The CPU path applies optional local LUT/grain, deterministic fps resampling, bilingual PNG overlays,
optional local music/voiceover mixing and an explicit silence track otherwise. Pillow's BASIC layout
receives Arabic reshaping plus bidi visual order exactly once; the bundled Noto Naskh Arabic font
and its OFL license are included. Font/LUT/audio bytes, prompts, motion seeds and settings are
recipe inputs. Text is painted in post, never requested from motion models. Music needs rights
credit; voiceover needs its language. No audio API is called.

ffprobe verifies actual H.264, yuv420p, 1080×1920, 30 fps, duration, AAC/48 kHz, configured size
limit and parsed MP4 moov-before-mdat faststart. Contact sheets contain one frame per second.
Low-resolution consecutive-frame luminance differences are recorded as a simple temporal proxy,
excluding edit cuts. This is not a measured DINO/VBench score. `VisualQA` accepts independent
subject/background/seam, semantic and palette evidence; missing evidence keeps `needs_review`,
not `passed`. Synthetic evidence cannot validate native footage. Failing spec produces no complete
artifact. Pending visual QA/reference footage is flagged in the human queue without a pointless
caption revision. Thresholds are configurable recipe settings, not established model performance.

Every generated-footage reel sets `ai_disclosure=true` and appends “Scenes created with AI.” and
“مشاهد أُنشئت بالذكاء الاصطناعي.” through `Post.full_caption`. Ken Burns of a real/synthetic still
alone is not claimed to be diffusion footage. Generated stills still require disclosure.
C2PA integration and Instagram API labels remain HUMAN spike/go-live items.

## Private worker

`gpu_worker/server.py` is a FastAPI factory. `/health` returns only status/backend. `POST /jobs`
returns a recipe-hash job ID; `GET /jobs/{id}` returns persisted status/artifact URLs. Job/artifact
routes require a header token from the git-ignored `.env` (`INSTABAY_WORKER_TOKEN`). Exact retries
return the same SQLite queue row. A single claim plus the render process lock serializes work.
A crashed running claim remains held; failed native jobs also hold the queue until external
reconciliation. The service never blindly resubmits uncertain ComfyUI jobs. Stub failures may be
re-rendered from exact inputs, while native incomplete recipes require human reconciliation.

# HUMAN: restrict Tailscale ACLs to tagged trusted devices, set a strong token, and bind only the
Tailscale address. Never expose this service publicly. The worker is not deployed by this phase.

```sh
# HUMAN: from the prepared gpu-box project, using conda main; export .env variables first.
~/miniconda3/envs/main/bin/python -m uvicorn gpu_worker.server:app_from_env \
  --factory --host 100.109.90.64 --port 8000 --workers 1
```

Native startup requires `INSTABAY_WORKER_RECIPE` and verifies its complete input/weight hashes.
Use a human-built image pinned by digest and a read-only weight/input volume; record its actual
GPU/driver/torch/CUDA/package identity in the recipe. CPU Docker acceptance does not establish
GPU image compatibility. Do not install another torch on the prepared Blackwell machine.
`WorkerClient` supplies authenticated, idempotent submission, bounded backoff polling and
SHA-256-verified downloads. `WeekRunner` accepts a `RenderService` and exact per-slot native
recipes for explicitly configured human runs; it never chooses a native model automatically.

## Native adapter limits

- **WanDiffusersBackend:** lazy optional imports; explicit `--confirm-gpu`, Linux and
  `INSTABAY_VIDEO_ENABLED=1`; offline local checkpoint only, entire directory hash manifest,
  measured runtime/package checks, fresh CPU seed generator, deterministic flags, TF32 off and
  CPU offload. Supports the configured I2V pipeline; LoRA application is refused. Scheduler settings,
  frames/resolution and FLF must match the human-tested checkpoint. No claim that a model fits
  this 16 GB box. Pipeline loads one shot at a time; memory/speed remain unmeasured.
- **ComfyUIBackend:** private origin, hashed API-format workflow, required bindings for every seed,
  prompt/negative prompt, resolution, frames, steps, CFG, shift and approved image/end image.
  Validates uploads/job IDs, bounded history polling, error states and one safe MP4 output.
  Custom-node commits are recorded; HUMAN must verify the running server actually uses them,
  along with its runtime, model files and deterministic launch flag. Synthetic transport tests
  do not establish server compatibility. Output subfolders are intentionally refused.
- **Veo/LTX:** pending comparison/stretch work. `--backend veo` fails explicitly; no paid request,
  fake fallback, invented price, preference score or cost saving is produced.

The [Diffusers Wan documentation](https://huggingface.co/docs/diffusers/en/api/pipelines/wan)
describes `last_image` for an FLF example; that does not prove every Wan checkpoint supports it.
The [official ComfyUI routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
describe prompt/history/view transport. Selected checkpoint/workflow behavior needs a real spike.

## Reproducibility and human work

L0 is the product guarantee: exact recipe → verified stored bytes. Two independent CPU test
renders compare every decoded frame; this establishes replay only on that tested runtime.
`golden` writes both frame-hash arrays and their equality. No cross-machine bitwise guarantee,
GPU L1, SSIM/LPIPS result or semantic QA pass rate is claimed. `render-golden.yml` is scheduled
but disabled unless `INSTABAY_GPU_GOLDEN_ENABLED=1`; it uses only a trusted self-hosted gpu-box
runner and human-prepared recipe/runtime, never pull-request inputs.

# HUMAN: record Phase 0 results in `docs/adr/0000-spikes.md`, prepare pinned weights/runtime,
verify FLF/memory, run uncached GPU golden comparisons and independently assess footage/Arabic.
Provide real DINO/Qwen-VL evidence and review threshold behavior before native QA can pass.
Enable the trusted runner only after those checks. No GPU inference/download/training, real
approval, live publication or paid benchmark happened in Phase 7.
