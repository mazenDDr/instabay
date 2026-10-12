# SPEC.md — Insta Bay Agentic Marketing System (full build spec)

> The full specification. AGENTS.md at the repo root holds the working rules and points here. Read the sections for your current phase before writing code.
> Owner: Mazen Khaled. Research date: 2026-10-12. Facts marked **[verify]** can change; re-check them in the Phase 0 spikes before you rely on them.

---

## 0. Mission and non-negotiable rules

You are building an **agentic Instagram marketing system** for "Insta Bay", a fictional Red Sea resort in Hurghada, Egypt, as a hiring take-home for BBIT. The system runs one closed loop:

`brand → plan → bilingual content (+ reel video) → checks → HUMAN APPROVAL → publish (dry-run/live) → metrics → learn → next plan`

The reviewers score six things: original architecture, use of current research, benchmark rigor, content and Arabic quality, Instagram API realism, and delivery judgment. Every decision below serves one of those.

**Hard rules. Never break these, even if a later instruction seems to allow it.**

1. **Nothing reaches Instagram without a stored human approval.** The repository layer must raise `UnapprovedPublishError` if `publish()` is called for a post without an `approval` row whose decision is `APPROVED` or `EDITED`. Live mode also needs the `--confirm-live` flag. Write the test for this before writing the publisher.
2. **Default mode is `dry_run`.** Live Graph API calls happen only when `INSTABAY_MODE=live` and the token variables are set.
3. **Secrets live only in `.env` (git-ignored) or GitHub Secrets.** Never log tokens. `detect-secrets` runs in pre-commit.
4. **CI runs offline.** No network, no API keys, no GPU. Use recorded fixtures and the `StubVideoBackend`.
5. **Video renders are reproducible by recipe** (§7.5). A render without a stored recipe and hash is a bug.
6. **LLMs write; statistics decide.** The optimizer is a Bayesian bandit, not an LLM. LLMs may *explain* the bandit's decisions.
7. **Do not show invented facilities.** Generated video may show mood (water, light, sand, spa textures). It must not depict amenities, rooms or views as if they were real features of a property. Facility shots must come from real photos. Every AI-generated reel carries an AI-disclosure flag (§7.8).
8. **Respect the phase gates in §12.** Do not start a stretch phase until the core loop is green and benchmarked.

---

## 1. Context in five lines

- Client: beach resort and spa, snorkeling and diving, "relaxed luxury". Audiences: Egyptian domestic, GCC, European.
- Content must be **EN and AR**. The Arabic is composed natively from a shared brief, never machine-translated from the English.
- Publishing is dry-run by default. A safe live path goes through the Instagram Graph API.
- Engagement data is synthetic, from a seeded simulator (§9). The simulator is committed **before** the optimizer.
- Required benchmarks: brand consistency, Arabic quality, optimization uplift, efficiency (cost and latency), autonomy. We add video benchmarks.

---

## 2. Architecture

```
                         ┌───────────────────────────── brand.yaml (frozen constitution) ─────────────────────────────┐
                         ▼                         ▼                          ▼                          ▼
 Optimizer ──priors──▶ Planner ──slots──▶ Brief Writer ──brief──▶ EN/AR Copywriters ──drafts──▶ CHECK CASCADE
 (Thompson)            (code)            (LLM)                    (LLM, parallel)              ├─ Rules (code)
     ▲                                        │                                                 ├─ System-1: Laya / Jev (typed decisions, calibrated)
     │                                        └──shot list──▶ VIDEO STUDIO (reels)              └─ System-2: LLM judge (other model family), only on low confidence
     │                                                         keyframes → I2V/FLF2V → post → QA          │
     │                                                                                                     ▼
 Insights ◀── 48 h ── Publisher (dry-run | Graph API) ◀── approved only ── HUMAN APPROVAL (CLI / Streamlit; GitHub Environment for live)
 (sim | Graph)                                                                   │
                                                                                 └── Analyst (LLM) writes the weekly "why" report
```

**Orchestration:** LangGraph `StateGraph` with `langgraph-checkpoint-sqlite`. Use `interrupt()` at the approval node. Video rendering is **not** a graph node that blocks. The graph enqueues a render job and resumes when the job completes (§7.6).

**Optional, behind a flag:** run the same graph on Temporal using `temporalio[langgraph]` (public preview since July 2026 **[verify]**). Nodes become activities with retries, and approval waits cost nothing while paused. Do this only if Phase 4 has time. SQLite checkpointing is enough for the submission.

---

## 3. Repository layout

```
instabay-agent/
├── AGENTS.md  README.md  Makefile  pyproject.toml  uv.lock  Dockerfile  .env.example  .pre-commit-config.yaml
├── .github/workflows/{ci.yml, bench.yml, weekly-cycle.yml, render-golden.yml}
├── config/{settings.py, brand.yaml, models.lock.yaml, render_presets.yaml}
├── src/instabay/
│   ├── core/        schemas.py rules.py planner.py optimizer.py recipe.py
│   ├── agents/      brand_architect.py brief_writer.py copy_en.py copy_ar.py judge.py analyst.py
│   ├── decisions/   engine.py (DecisionEngine protocol) laya_local.py jev_http.py calibration.py
│   ├── video/       shotlist.py keyframes.py backends/{stub,wan_diffusers,comfyui,veo}.py post.py qa.py worker.py
│   ├── adapters/    publisher.py insights.py media.py storage.py
│   ├── prompts/     *.md (Arabic prompts written in Arabic) — versioned, hashed into run logs
│   ├── graph.py  llm.py  db.py  cli.py
├── sim/  bench/  tests/{unit,contract,integration,determinism}/  tests/fixtures/
├── gpu_worker/      Dockerfile.gpu  server.py (FastAPI render service for gpu-box)  requirements.lock
├── outputs/  docs/{BRAND.md, RESEARCH.md, GO_LIVE.md, ARCHITECTURE.md, adr/}
```

---

## 4. Tech stack

| Concern | Choice | Notes |
|---|---|---|
| Runtime | Python 3.12, `uv`, `uv.lock` | Pin everything |
| Orchestration | LangGraph + SQLite checkpointer | `interrupt()` for approval |
| Schemas | Pydantic v2 | All LLM outputs are schema-validated |
| LLM access | One `LLMClient` protocol (litellm or provider SDKs) | Logs tokens, cost and latency; caches by prompt hash |
| Generator LLM | Gemini Flash tier via Google AI Studio **[verify current model ID and free quota]** | Strong Arabic |
| Judge LLM | A different family (Llama or Qwen via Groq) **[verify]** | Reduces self-preference bias |
| System-1 decisions | **Laya** (`pip install laya`, Apache-2.0); Jev via HTTP if access is granted | §6 |
| Storage | SQLite via SQLModel | §10 |
| Video (open) | Wan 2.2 (Apache-2.0) via diffusers on gpu-box; LTX-2.5 optional | §7 |
| Video (paid comparison) | Veo 3.1 via Gemini API | §7.7 |
| Keyframe images | Real photos first; Qwen-Image / Qwen-Image-Edit (Apache-2.0) **[verify license]** for generated stills | Avoid FLUX.1 [dev]: its license is non-commercial |
| Video QA | Qwen3-VL (open VLM) as frame judge; DINOv2/CLIP frame similarity; ffprobe | §7.7 |
| Voice-over | AR: Habibi (F5-TTS based, Arabic dialects) **[verify license]**; EN: an open TTS | Optional |
| Post | ffmpeg, `arabic-reshaper` + `python-bidi`, Noto Naskh Arabic / Cairo font (OFL) | Text is overlaid in post, never generated by the video model |
| Provenance | `c2pa-python` content credentials on rendered MP4/JPEG **[verify]** | Supports the AI-disclosure rule |
| Quality | ruff, mypy, pytest, pytest-recording, hypothesis, pre-commit | |

---

## 5. Module specs (core loop)

Every module is a pure function or a class behind a `Protocol`. Each spec lists input → output → acceptance criteria. Cite the requirement ID (FR-xx) in the docstrings.

### 5.1 Brand Architect (FR-01)
- In: the brief text. Out: `BrandConstitution` → `config/brand.yaml`.
- Fields: `positioning`, `voice.en.{do,dont,examples}`, `voice.ar.{register, do, dont, examples}`, `pillars[5]{id, description, min_share, max_share}`, `hashtags.{branded, place, niche, broad}` (EN + AR), `cadence.{posts_per_week, reels_per_week, windows_cairo}`, `visual.{palette_hex, photo_direction, banned}`, `claims_policy` (no invented facilities, no prices without an offer source).
- Accept: schema-valid. Pillar `min_share` values sum to ≤ 1 and `max_share` values sum to ≥ 1. A human edits the file once, then a hash is stored in `brand_version`.
- Arabic register default: light MSA, Gulf- and Egypt-friendly. Make it a config value.

### 5.2 Planner (FR-02, FR-03)
- In: optimizer posterior + brand bounds. Out: 7 `Slot{scheduled_at (Africa/Cairo), arm{pillar, format, time_bucket, hook_style}, segment}`.
- Constraints: pillar shares inside their bounds; ≥ 1 reel per week; no posts between 01:00 and 07:00 Cairo time; at least 1 exploration slot per week.
- Accept: a hypothesis property test shows the constraints hold for any posterior.

### 5.3 Brief Writer + Copywriters (FR-04, FR-05, FR-06)
- The brief is language-neutral: `angle, hook, key_message, visual_description, cta, shot_list?` (reels only).
- EN and AR writers run in parallel from the same brief. The AR system prompt is written in Arabic with Arabic few-shot examples.
- The hashtag selector is code, not an LLM: 8–15 tags from the tiered bank, ≥ 1 branded tag, at most 30.
- Accept: caption ≤ 2,200 chars; ≤ 30 hashtags; ≤ 20 @ tags; AR text has an Arabic-script ratio ≥ 0.9; no banned terms.

### 5.4 Check cascade (FR-08), the reliability core
Three tiers, cheapest first:

1. **Rules (code):** the length and count limits above, banned words, emoji budget, price claims without an offer ID, "invented facility" keywords.
2. **System-1 (Laya / Jev):** typed questions, each answered with a calibrated confidence (§6.2).
3. **System-2 (LLM judge):** a G-Eval-style rubric 1–5 from a different model family, temperature 0, 3 samples averaged. Called only when a System-1 confidence is below its fitted threshold, or for a random 10% audit sample. The audit sample keeps System-1 honest.

On failure: run one Self-Refine revision with the judge's fixes. If the draft still fails, it goes to the human with `flagged=True`.

### 5.5 Approval (FR-09)
- A CLI (`typer` + `rich`) showing EN | AR side by side, scores, flags, and a video preview path. Decisions: approve / edit / reject + reason.
- Store edit diffs. They become training data for GEPA (§8.1) and for Laya's fine-tune (§6.3).
- Time every decision. That feeds the Autonomy metric.

### 5.6 Publisher and Insights (FR-10, FR-11)
- See §11 for exact Graph API facts.
- `Publisher` protocol: `DryRunPublisher` (writes to `outbox/` and feeds the simulator) and `GraphPublisher`.
- `InsightsSource` protocol: `SimulatedInsights` and `GraphInsights`. Both return the same schema, stored in long format.

---

## 6. Decision layer: Laya and Jev (System-1)

### 6.1 What they are
- **Jev** (TypeSafe, announced 2026-09-15) is a hosted "System One" model. It answers typed questions (`choice`, `score`, `noul` = yes/no probability) about unstructured input in one parallel pass, with schema-constrained outputs and a training method called RLCD (reinforcement learning for calibrated decisions). Endpoint: `POST https://api.typesafe.ai/v1/systemone`. Early access via waitlist. The vendor reports 67.8% accuracy at $0.0004 and 0.4 s per case, versus 67.9–74.1% at $0.03–0.18 and 10–38 s per case for frontier LLMs, on its own 4-workflow benchmark. That benchmark is not independently reproduced. Source: DataCamp's write-up (§14).
- **Laya** (`NandhaKishorM/laya`, Apache-2.0, `pip install laya`) is an open, self-hostable decision engine whose `laya-serve` HTTP server speaks the same `/v1/systemone` wire protocol. Checkpoints: `laya` (ModernBERT-large, 421M, English), `laya-multilingual` (mmBERT-base, 322M, 100+ languages), `laya-typed-decisions` (fine-tuned). A `Router` sends non-Latin scripts, including Arabic, to the multilingual checkpoint. It ships LangGraph integrations (`LayaRouter`, `LayaGuardrail`, `LayaDecision`), ONNX, and an MCP server.
- **Self-reported numbers to keep in mind:** about 33 ms for one question and 7.2 ms per question batched on a T4. MASSIVE intent: 0.783 for English, 0.451 for the multilingual checkpoint across 13 other languages. Fine-tuned typed decisions: 0.766 vs 0.362 for the base checkpoint. **The README says both checkpoints are over-confident as shipped and `laya-multilingual` has no fitted temperatures.** You must calibrate before trusting any threshold. There are no Arabic-specific results.
- **Not yet tested by us.** Model download from Hugging Face was blocked in the research sandbox. The Phase 0 spike (§12) must test it on gpu-box.

### 6.2 Where System-1 is used (all behind the `DecisionEngine` protocol)

| # | Use | Question type | Why it helps |
|---|---|---|---|
| D1 | **Plan-execution fidelity:** does the caption actually use the planned `hook_style` and pillar? | `choice` | The bandit only learns correctly if the arm it chose is the arm that was executed. This is the most valuable use |
| D2 | Brand checks: hard-sell language, luxury tone level, register (MSA vs dialect) | `noul`, `score`, `choice` | Cheap first pass before the LLM judge |
| D3 | Safety guardrail on untrusted text (comments, trend inputs) entering prompts | `LayaGuardrail` | Prompt-injection defense |
| D4 | Approval-queue ordering: probability the human approves | `noul`, fine-tuned on approval logs | Sorts the queue. **Never auto-approves** |
| D5 (go-live) | Comment and DM triage: booking intent / question / complaint / spam | `choice` | Routes to the right human fast |

```python
class DecisionEngine(Protocol):
    def decide(self, state: str | dict, questions: dict[str, Question]) -> dict[str, Answer]: ...
# Implementations: LayaLocalEngine (in-process Router), SystemOneHTTPEngine(base_url) — the same class
# talks to laya-serve on gpu-box OR to Jev by changing base_url and auth header.
```

### 6.3 Calibration and fine-tuning protocol
1. Build a gold set of 300 bilingual items (≥ 40% Arabic) for D1 and D2. Labels come from the LLM judge, and a human audits a 60-item subset. Split 60/20/20.
2. Measure zero-shot accuracy and **ECE** (expected calibration error) per language.
3. Fit per-question temperatures and abstention thresholds on the validation split with Laya's calibration utilities (`fit_abstention_thresholds`, `fit_binning_map`, and others; read `docs/` in the repo **[verify API]**). Target: ≥ 95% precision on the non-abstained set.
4. If Arabic accuracy is below 0.8 after calibration, fine-tune `laya-multilingual` with the repo's typed-decisions notebook on gpu-box, then re-calibrate.
5. Report: escalation rate, cost and latency saved vs. judge-only, and agreement with the human subset. This becomes a benchmark row (§9).

**Kill criterion:** if System-1 cannot reach 95% precision while escalating fewer than 70% of items, keep it only for D1 and D3 and say so in RESEARCH.md. An honest negative result scores better than a hidden one.

---

## 7. Video Studio (reels)

### 7.1 Design principles
- **Keyframes first, motion second.** Every shot starts from an approved still. Motion models are good at adding modest motion to a strong image, and weak at inventing a whole scene from text.
- **Short shots, pinned ends.** Shots are 3–5 s. Join consecutive shots with **first-last-frame (FLF) conditioning**, so the end of shot N is the start of shot N+1.
- **Text and logos are added in post,** never generated by the model. Arabic text needs reshaping + bidi + an Arabic font.
- **Avoid identifiable faces by default** (hands, silhouettes, backs, water, textures). This lowers deepfake and identity-drift risk.
- **Every render is a pure function of its recipe** (§7.5).

### 7.2 Shot list schema (output of the Brief Writer for reels)
```yaml
reel_id: wk03-reel-01
duration_s: 18            # 15–30 s target, IG allows 3 s–15 min
aspect: "9:16"            # 1080x1920 final
shots:
  - id: s1
    role: hook            # first 0–3 s must stop the scroll
    keyframe: {source: photo, uri: "assets/photos/reef_01.jpg"}   # or {source: generated, prompt: ..., seed: ...}
    end_keyframe: s2      # FLF: this shot ends on shot s2's keyframe
    motion_prompt: "slow push-in under turquoise water, sunlight caustics on coral, gentle fish movement"
    camera: push_in       # enum: static|push_in|pull_out|pan_left|pan_right|orbit|tilt_up|tilt_down
    seconds: 4
    overlay: {en: "Your morning commute.", ar: "مشوارك الصباحي."}
audio: {music: library_track_id | generated, voiceover: {lang: ar, text: "..."} | null}
disclosure: ai_generated_scenery   # §7.8
```

### 7.3 Pipeline stages
1. **Keyframes.** Use a real photo if one exists (best realism, honest). Otherwise generate with Qwen-Image. For continuity across shots, *edit* a previous keyframe with Qwen-Image-Edit (same scene, new angle or time of day) instead of generating from scratch. Color-match all keyframes to the brand LUT.
2. **Motion.** Image-to-video per shot. Use FLF when `end_keyframe` is set. Backends (§7.4).
3. **Continuity check.** Measure DINOv2 cosine similarity between the last frame of shot N and the first frame of shot N+1. It must be ≥ the threshold in `render_presets.yaml`. If FLF is unavailable, chain the extracted last frame of N as the input to N+1, but **re-anchor** to an approved keyframe at least every 2 shots to stop drift.
4. **Post.** Optional upscale (e.g., an open video upscaler) → frame interpolation to 30 fps (RIFE) → brand LUT → light film grain → text overlays (ffmpeg drawtext with shaped Arabic) → audio mix → encode with the IG reel spec: `-c:v libx264 -pix_fmt yuv420p -r 30 -c:a aac -ar 48000 -b:a 128k -movflags +faststart`, 1080×1920, ≤ 300 MB.
5. **QA** (§7.7), then to the approval queue with a contact sheet (1 frame per second) and the MP4.

### 7.4 Backends (all implement `VideoBackend`)
```python
class VideoBackend(Protocol):
    name: str
    def capabilities(self) -> BackendCaps: ...   # i2v, flf2v, max_seconds, resolutions, audio, deterministic
    def render_shot(self, shot: ShotRecipe) -> RenderResult: ...  # returns mp4 path + frame hashes + timings
```

| Backend | Where | Use |
|---|---|---|
| `StubVideoBackend` | CI, laptop | ffmpeg Ken Burns over the keyframe. Deterministic, no GPU |
| `WanDiffusersBackend` | gpu-box (primary) | Wan 2.2 via diffusers. Pick the variant by VRAM (below) |
| `ComfyUIBackend` | gpu-box (alternative) | POST workflow JSON to ComfyUI's HTTP API (`/prompt`, `/history/{id}`, `/view`). Useful for community workflows (Wan2.2 14B FLF2V, Lightning 4-step LoRAs, GGUF quantization). Pin custom nodes by git commit |
| `VeoBackend` | Gemini API (paid) | Comparison and fallback (§7.7) |

**Variant choice by VRAM on gpu-box** (run `nvidia-smi` in the Phase 0 spike):

| VRAM | Model | Notes from the official repo |
|---|---|---|
| 24 GB | Wan2.2-TI2V-5B, 1280×704 / 704×1280 at 24 fps | Stated: a 5 s 720p clip in < 9 min on one consumer GPU (RTX 4090 class) |
| 24–48 GB | Wan2.2-I2V-A14B with FP8/GGUF quantization + CPU offload, or Wan2.2-Lightning 4-step LoRAs | Community quantization and distillation. Quality must be checked. Lightning claims ~20× speed-up |
| ≥ 80 GB | Wan2.2-I2V-A14B full precision | Official single-GPU requirement for A14B |
| ≥ 32 GB (FP8) | LTX-2.5 (22B, native synchronized audio, keyframe interpolation, retake) | Optional second open backend. LTX license is free for companies under $10M ARR **[verify]** |

**FLF2V:** ComfyUI ships an official "Wan 2.2 14B First-Last Frame to Video" workflow. In diffusers, check whether `WanImageToVideoPipeline` accepts `last_image` for the chosen checkpoint **[verify in spike]**. If not, use the ComfyUI backend for FLF shots.

### 7.5 Determinism protocol (reproducible renders)
There are three levels. Claim only the level you have measured.

- **L0, artifact reproducibility (always guaranteed):** `recipe_hash = sha256(canonical_json(recipe))`. The recipe holds model repo + revision SHA, weight file hashes, LoRA hashes, pipeline class, scheduler + config, steps, CFG, shift, resolution, frames, fps, seed, keyframe image hashes, prompt text, negative prompt, the docker image digest, torch/CUDA/driver versions, and the GPU name. Renders are stored content-addressed under `renders/{recipe_hash}/`. The same recipe returns the stored file. This is the guarantee the product relies on.
- **L1, bitwise re-render on the same machine:** fixed `torch.Generator("cpu").manual_seed(seed)`, created fresh for each call. Set `CUBLAS_WORKSPACE_CONFIG=:16:8`, `torch.use_deterministic_algorithms(True)`, `torch.backends.cudnn.benchmark=False`, and TF32 off (or call diffusers' `enable_full_determinism()`). Batch size 1. No `torch.compile` autotuning. Avoid attention kernels that are not deterministic. For ComfyUI, launch with `--deterministic` and fix the seed widget. **Test:** `tests/determinism/` renders the golden recipe twice and compares the SHA-256 of every decoded frame. The `render-golden.yml` workflow runs this nightly on gpu-box (self-hosted runner over Tailscale) and fails on any mismatch.
- **L2, cross-machine (different GPU or driver):** not bitwise. Diffusers' own docs say results match only within a tolerance. Assert perceptual equivalence instead: SSIM ≥ 0.98 and LPIPS ≤ 0.02 per frame against the golden render. Document this honestly.
- **Paid APIs are not deterministic.** Veo's `seed` "doesn't guarantee determinism" per Google's docs. Paid renders are therefore L0 only: cached by recipe, never re-generated.

### 7.6 Render worker on gpu-box
- `gpu_worker/server.py`: FastAPI with `POST /jobs` (recipe) → job ID; `GET /jobs/{id}` → status and artifact URLs; one GPU job at a time; a SQLite queue; idempotent by `recipe_hash`.
- Reached only over **Tailscale** (`http://gpu-box:PORT` via MagicDNS). Never expose it to the public internet. Restrict access with Tailscale ACLs to tagged devices.
- Use a Docker image pinned by digest, with weights in a read-only volume and verified by hash on start-up.
- The LangGraph node `render_reel` submits the job, then the graph waits for completion. Use a polling node with backoff, or Temporal if enabled.

### 7.7 Video QA and the open-vs-paid benchmark
**Automatic QA gate** (all must pass, or the reel is flagged):
- Spec: ffprobe confirms codec, pixel format, fps, resolution, duration, faststart, and size ≤ 300 MB.
- Temporal: VBench-style subject and background consistency (DINOv2 / CLIP similarity of consecutive frames), a flicker score, and the seam score between shots.
- Semantic: Qwen3-VL watches the frames and answers typed questions (does shot s1 show underwater coral? any distorted hands or faces? any visible gibberish text?). Use the same `choice/noul` style as §6.
- Brand: a color histogram distance to the brand palette.

**Open-vs-paid study** (a stretch goal, worth a lot in the README):
- 6 shot recipes × 3 backends (Wan 2.2 local, LTX-2.5 local if there is VRAM, Veo 3.1 Fast). Same keyframes, same motion prompts.
- **Blind pairwise preference:** 3+ raters see randomized pairs and pick the more realistic, more on-brand shot. Report win rates with a Bradley–Terry score and 95% bootstrap CIs.
- Also report cost per second, wall time per second, determinism level (L1 vs L0-only), and QA pass rate.

Reference prices and limits **[verify]**: Veo 3.1 per second with audio: Standard $0.40 (720p/1080p), Fast $0.10–0.12, Lite $0.05–0.08. No free tier. 4/6/8 s clips at 24 fps, 9:16 supported. Image-to-video, `lastFrame`, up to 3 reference images, extension +7 s up to 20 times (720p only). Outputs stored 2 days. SynthID watermark. Only English is "fully supported". Under EU, UK, CH and MENA rules only `allow_adult` person generation is permitted. Text-to-video and extension on Veo 3.1 accept only `allow_all`, so **from Egypt (MENA), shots with people may only work through image-to-video, interpolation or reference images** **[verify in spike]**. This is one more reason to keep the keyframe-first design and avoid identifiable faces.

### 7.8 Disclosure and provenance
- Set `post.ai_disclosure = true` for any reel containing generated footage, and add a caption line (EN + AR) such as "Scenes created with AI".
- Attach C2PA content credentials to the rendered file if `c2pa-python` works in the spike. The EU AI Act requires professional deployers to disclose certain deepfakes from 2026-08-02. Meta labels AI content as "AI info" from creator disclosure or detected signals such as C2PA.
- Check in the go-live phase whether API-published media can carry Instagram's AI label **[unknown, verify]**. Until then the caption line is mandatory.

---

## 8. Reliability layer

### 8.1 Prompt optimization with GEPA
GEPA (Agrawal et al., arXiv:2507.19457) evolves prompts by reflecting on rollouts in natural language and keeping a Pareto front of candidates. The paper reports beating GRPO by about 6% on average with up to 35× fewer rollouts, and MIPROv2 by more than 10%. Code: `github.com/gepa-ai/gepa` **[verify the DSPy integration]**.
- Use it **offline** on the AR copywriter and the brief writer. Metric = the judge's rubric score + Laya D1 fidelity + rule pass rate. Feedback text = the judge's rationale + the human's edit diffs.
- Budget: ≤ 150 rollouts. Freeze the winning prompt, hash it, and report before → after on a held-out set. Never optimize against the test set.

### 8.2 Other reliability mechanisms
- **Schema-first:** every LLM call returns Pydantic models. On a validation failure, retry once with the error message, then fail loudly.
- **Idempotency:** each post has `idempotency_key = hash(slot_id, brand_version, prompt_hashes)`. The publisher checks `status_code == PUBLISHED` before retrying `media_publish`.
- **Budgets:** per-run caps on tokens, $, and GPU minutes. When a cap is hit, the run stops cleanly with a report.
- **Golden-set regression:** 20 frozen briefs re-generated in CI from cassettes, and in `bench.yml` live. Fail if the brand score drops by more than 0.3.
- **Observability:** one row in `llm_call` / `render_job` per call. Optional OpenTelemetry export.
- **Fallback chain:** generator LLM → secondary provider; Wan → Stub (and flag the reel); Laya → LLM judge.

---

## 9. Simulator and optimizer (unchanged from the plan)
- Hidden audience per seed: `reach ~ LogNormal(μ0 + r_format + r_time, σ)`; `logit p = b0 + β_pillar + β_format + β_time + β_hook + ε`; β ~ Normal(0, 0.3) drawn from the seed. Counts are Binomial. Reel watch-through is Beta-distributed and tied to the hook.
- Optimizer: factored Thompson sampling, one Beta posterior per factor level. Planner constraints apply.
- Protocol: 12 weeks × 7 posts × 20 seeds. Policies: fixed week-1 plan (before), uniform random, Thompson (after), oracle. Report uplift in weeks 9–12 with a 95% bootstrap CI, plus cumulative regret.
- **New:** use the D1 fidelity check to measure "arm leakage" (planned arm ≠ executed arm) and show its effect on regret. That is a novel and defensible result.

---

## 10. Data model (SQLite, 3NF)
`brand_version`, `arm` (candidate key pillar+format+time_bucket+hook_style), `slot`, `post` (+ `ai_disclosure`, `idempotency_key`), `judge_score`, `decision_score` (engine, question_id, answer, confidence, escalated), `approval`, `publication`, `metric` (long format), `posterior`, `llm_call`, `render_job` (recipe_hash PK, backend, status, gpu, seconds, frame_hashes_json, qa_json, cost_usd).

---

## 11. Instagram Graph API facts (source: Meta developer docs, read 2026-10)
- Latest API version shown: **v25.0**. Pin it in config.
- Instagram Login path: `graph.instagram.com`, scopes `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights`. No Facebook Page needed.
- Facebook Login path: `graph.facebook.com` (+ `rupload.facebook.com` for resumable upload), scopes `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`, `instagram_manage_insights`.
- Publish: `POST /{ig-id}/media` → poll `GET /{container}?fields=status_code` (IN_PROGRESS / FINISHED / ERROR / EXPIRED / PUBLISHED; about once a minute, ≤ 5 min) → `POST /{ig-id}/media_publish?creation_id=`.
- Reels: `media_type=REELS`, `video_url` or resumable upload, `cover_url` / `thumb_offset`, `share_to_feed`. Published media reports `media_type=VIDEO`; check `media_product_type`.
- Limits: 100 API posts per rolling 24 h (the same page says 50 for carousels, so cap at 50). Check `GET /{ig-id}/content_publishing_limit`. Containers expire after 24 h. Captions ≤ 2,200 chars, ≤ 30 hashtags, ≤ 20 @ tags. Images JPEG only, ≤ 8 MB, aspect 4:5 to 1.91:1. Reels: MP4/MOV, H.264/HEVC, AAC ≤ 48 kHz, 23–60 fps, ≤ 1,920 px wide, 3 s–15 min, ≤ 300 MB, moov atom at the front. Carousels ≤ 10 items.
- Insights: use `views`, not `impressions` or `plays` (deprecated in v22.0 / April 21, 2025). Reels add `ig_reels_avg_watch_time`. Data can lag up to 48 h. Missing data comes back as an empty set. Carousel children have no insights.
- Media URLs must be public at publish time. Upload to a public bucket first and check for HTTP 200.

---

## 12. Phases and gates
The build phases, their order and their gates are defined in **AGENTS.md** (repo root). That table is the single source of truth. The human runs the Phase 0 spikes (GPU box render and determinism check, Laya on 30 EN + 30 AR captions, current model IDs and quotas, `last_image` FLF support) and records them in `docs/adr/0000-spikes.md`.

**Scope warning:** the core loop alone exceeds the brief's 5–6 hour guideline, and the decision layer and video studio add much more. Keep the README honest about what was built, what was stubbed, and the time spent.

---

## 13. Commands the repo must support
```
make setup      # uv sync, pre-commit install
make demo       # 1 simulated week, dry-run, stops at approval, resumes
make test       # offline: unit + contract + integration (+ determinism skipped without GPU)
make bench      # writes bench/results.json and the README table
make render RECIPE=outputs/wk03-reel-01.yaml BACKEND=wan   # via gpu-box worker
make golden     # determinism check on gpu-box
instabay cycle --weeks 3 [--live --confirm-live]
```

---

## 14. References
- Laya: https://github.com/NandhaKishorM/laya
- Jev overview: https://www.datacamp.com/blog/system-one-models-jev
- GEPA: https://arxiv.org/abs/2507.19457
- Self-Refine: https://arxiv.org/abs/2303.17651 · G-Eval: https://arxiv.org/abs/2303.16634 · LLM-as-a-judge: https://arxiv.org/abs/2306.05685 · Self-preference bias: https://arxiv.org/abs/2404.13076 · Thompson sampling tutorial: https://arxiv.org/abs/1707.02038
- Building effective agents (Anthropic): https://www.anthropic.com/research/building-effective-agents
- Temporal LangGraph plugin: https://temporal.io/blog/temporal-langgraph-plugin-durable-execution
- Wan 2.2: https://github.com/Wan-Video/Wan2.2 · Wan2.2-Lightning: https://github.com/ModelTC/Wan2.2-Lightning · ComfyUI Wan 2.2 FLF2V workflow: https://comfy.org/workflows/video_wan2_2_14B_flf2v-7016f027bcf1/
- LTX-2: https://github.com/Lightricks/LTX-2 · Open-model landscape (LTX blog): https://ltx.io/blog/open-source-video-generation-models-guide
- Veo 3.1 docs: https://ai.google.dev/gemini-api/docs/veo · Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Video model rankings (Artificial Analysis arena, via Techsy, June 2026): https://techsy.io/en/blog/best-ai-video-models
- Sora shutdown (API ends 2026-09-24; do not build on it): https://en.wikipedia.org/wiki/Sora_(text-to-video_model)
- Diffusers reproducibility: https://huggingface.co/docs/diffusers/en/using-diffusers/reusing_seeds
- VBench-2.0: https://arxiv.org/abs/2503.21755
- Habibi Arabic TTS: https://arxiv.org/abs/2601.13802
- Instagram AI labels (guide, Aug 2026): https://www.gradually.ai/en/instagram-ai-label/
- Meta: content publishing https://developers.facebook.com/docs/instagram-platform/content-publishing · media reference https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media · insights https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights/

---

## 15. Worked examples (target shapes for schemas and tests)

These follow one post (slot `wk42-tue-1`) through the system. Use them as the shapes for Pydantic models and as test fixtures. The values are illustrative.

### 15.1 Brand Architect
Input (`config/brand_inputs.yaml`, filled by the human):
```yaml
brief: |
  Beach resort & spa on the Red Sea in Hurghada. Snorkeling, diving, relaxed luxury,
  "every moment worth posting". Guests: Egyptian domestic, GCC, European.
owner_answers:
  real_offers: ["Winter Escape: 4th night free, Nov-Feb"]
  must_avoid: [nightlife, alcohol imagery]
  tone_examples_they_like: ["Slow mornings. Salt in your hair."]
```
Output (`config/brand.yaml`, LLM draft → human edit → frozen, sha256 stored in `brand_version`):
```yaml
version: 3
positioning: "Relaxed luxury where the Red Sea is the main character."
voice:
  en: {do: [short sentences, sensory detail], dont: ["cheap", ALL CAPS, "> 2 emoji"]}
  ar: {register: light_msa, dont: [heavy dialect, transliterated English]}
pillars:
  - {id: underwater, min_share: 0.10, max_share: 0.40}
  - {id: spa,        min_share: 0.10, max_share: 0.40}
  - {id: guests,     min_share: 0.10, max_share: 0.40}
  - {id: local,      min_share: 0.10, max_share: 0.40}
  - {id: offers,     min_share: 0.10, max_share: 0.30}
hashtags:
  branded: ["#InstaBay", "#انستا_باي"]
  place:   ["#Hurghada", "#RedSea", "#الغردقة", "#البحر_الأحمر"]
  niche:   ["#RedSeaDiving", "#SnorkelEgypt"]
  broad:   ["#TravelEgypt", "#سياحة_مصر"]
cadence: {posts_per_week: 7, min_reels: 1, quiet_hours: "01:00-07:00 Africa/Cairo"}
claims_policy: {allowed_offers: [winter_escape_4th_night_free], no_invented_facilities: true}
```

### 15.2 Planner
Beliefs are Beta(α, β) per option of each factor. Mean = α/(α+β). Each post updates its options with **20 pseudo-observations**: α += 20·rate, β += 20·(1−rate), so one viral post cannot dominate.
Input:
```json
{"week": 42,
 "beliefs": {"pillar": {"underwater": [4.2, 56.8], "spa": [3.1, 57.9], "guests": [2.9, 58.1],
                        "local": [2.4, 58.6], "offers": [1.9, 59.1]},
             "format": {"photo": [3.0, 52.0], "carousel": [2.6, 50.4], "reel": [3.5, 46.5]},
             "time_slot": {"morning_08_10": [2.1, 49.9], "noon_12_14": [2.4, 47.6],
                           "evening_19_21": [3.3, 46.7], "late_21_23": [2.7, 47.3]},
             "hook_style": {"question": [3.2, 48.8], "statement": [2.8, 49.2], "number": [2.5, 47.5]}},
 "pins": [{"day": "fri", "pillar": "offers"}]}
```
Output (7 items):
```json
[{"slot_id": "wk42-tue-1", "when": "2026-10-20T19:30:00+03:00", "pillar": "underwater",
  "format": "photo", "time_slot": "evening_19_21", "hook_style": "question",
  "segment": "gcc", "explore": false}]
```

### 15.3 Brief Writer
```json
{"angle": "The quiet of the reef before anyone else is up",
 "hook": "Ask when they last heard real silence",
 "key_message": "Our house reef is a few steps from your room, calm at 8 am",
 "visual": "reef_01.jpg", "cta": "save for your next escape",
 "must_not": ["prices", "crowds", "faces"]}
```

### 15.4 Copywriters (hashtags added afterwards by code)
```json
{"en": {"caption": "When did you last hear real silence?\nOur house reef at 8 am: clownfish, turquoise light, nobody else. 🐠\nSave this for your next escape.",
        "alt_text": "Coral reef in clear turquoise water with clownfish, morning light"},
 "ar": {"caption": "متى آخر مرة سمعت صوت الهدوء الحقيقي؟\nالشعاب المرجانية أمام غرفتك في الثامنة صباحاً: سمك المهرج، ضوء فيروزي، ولا أحد غيرك. 🐠\nاحفظ المنشور لرحلتك القادمة.",
        "alt_text": "شعاب مرجانية في مياه فيروزية صافية مع سمك المهرج في ضوء الصباح"},
 "hashtags": ["#InstaBay", "#انستا_باي", "#Hurghada", "#الغردقة", "#RedSea", "#RedSeaDiving", "#SnorkelEgypt", "#TravelEgypt"]}
```

### 15.5 Rules result
```json
{"post": "wk42-tue-1", "passed": true,
 "checks": {"caption_len": {"en": 132, "ar": 141, "max": 2200}, "hashtags": {"count": 8, "allowed": "8-15"},
            "branded_tag": true, "arabic_ratio": 0.97, "emoji": 1, "banned_words": [],
            "price_mentions": [], "facility_claims": []}}
```

### 15.6 Laya / Jev request and response (`POST /v1/systemone`)
```json
{"state": "متى آخر مرة سمعت صوت الهدوء الحقيقي؟ ...",
 "questions": {
   "hook": {"type": "choice", "instructions": "Which hook style opens this caption?",
            "criteria": {"question": "opens with a question", "statement": "opens with a statement",
                         "number": "opens with a number or list"}},
   "hardsell": {"type": "noul", "instructions": "Does it use pushy sales language?"},
   "register": {"type": "choice", "instructions": "Which Arabic register is used?",
                "criteria": {"msa": "Modern Standard Arabic", "egyptian": "Egyptian dialect", "gulf": "Gulf dialect"}}}}
```
```json
{"answers": {"hook": {"choice": "question", "confidence": 0.94},
             "hardsell": {"noul": 0.03, "confidence": 0.92},
             "register": {"choice": "msa", "confidence": 0.71}},
 "routing": {"model": "multilingual"}}
```
`register` confidence 0.71 < fitted threshold 0.80 → only that question escalates to the judge.

### 15.7 Judge output
```json
{"scores": {"voice": 5, "pillar_fit": 5, "caption_visual_match": 4, "hashtag_policy": 5, "format_cta": 4},
 "average": 4.6, "samples": 3, "passed": true, "fixes": []}
```

### 15.8 Approval decision
```json
{"post": "wk42-tue-1", "decision": "EDITED", "reason": "softer CTA",
 "diff": {"en.caption": "- Save this for your next escape.\n+ Save this for a slower week."},
 "actor": "mazen", "seconds_spent": 41, "decided_at": "2026-10-18T20:12:05+03:00"}
```

### 15.9 Simulator output and optimizer update
```json
{"world_seed": 7, "reach": 1850, "views": 2410, "likes": 78, "comments": 6, "saved": 14, "shares": 6,
 "engagement_rate": 0.056}
```
Update: α += 20 × 0.056 = 1.12, β += 20 × 0.944 = 18.88 → `pillar.underwater` [4.2, 56.8] → [5.32, 75.68] (mean 6.9% → 6.6%). The same update applies to `format.photo`, `time_slot.evening_19_21` and `hook_style.question`, **only if** the D1 check confirmed the executed arm; otherwise the post is logged as leaked and not used for learning.

### 15.10 Reel render result
```json
{"file": "renders/3b9e41c0.../reel.mp4", "recipe_hash": "3b9e41c0...", "duration_s": 18.0,
 "size": "1080x1920", "fps": 30, "render_minutes": 37.5, "gpu": "RTX 4090 24GB",
 "qa": {"spec_ok": true, "seam_similarity": [0.93, 0.91, 0.94], "flicker": 0.02,
        "vision_checks": {"planned_scene": "yes", "distorted_hands": "no", "stray_text": "no"}},
 "ai_disclosure": true}
```

---

## 16. Benchmarks (exact definitions for `make bench`)

Run on a fixed set of 21 posts (3 weeks × 7). Write `bench/results.json` and render it into the README table.

| Metric | Exact definition | Method | Check on the measurement |
|---|---|---|---|
| Brand consistency (1–5) | Mean of 5 rubric dimensions: voice, pillar fit, caption–visual match, hashtag policy, format/CTA; each 1–5 with written anchors in `bench/rubric.md` | Judge LLM from a different family, temperature 0, 3 samples averaged; plus the hard-rule pass rate | Human labels 20 posts → quadratic-weighted Cohen's κ vs the judge. Negative control: 10 generic "any hotel" captions must score clearly lower |
| Arabic quality (1–5) | Fluency, naturalness, brand-voice match | Blind human rating: 20 native AR captions mixed with 20 machine translations of the EN captions, shuffled. Ratings in `bench/human_ratings/*.csv` (HUMAN) | Mean per version, win rate native vs MT, Krippendorff's α across raters. The LLM judge's Arabic score is reported next to it with its correlation to the humans |
| Optimization uplift | Relative change in engagement rate, weeks 9–12, Thompson sampling vs the fixed week-1 plan | 12 weeks × 7 posts × 20 seeds (§9) | 95% bootstrap CI; uniform-random and oracle baselines; cumulative regret |
| Efficiency | Tokens in/out, $ and latency per feed post and per reel | Summed from `llm_call` and `render_job`; p50 and p95 latency | $ reported at the provider's paid list price as well as actual spend |
| Autonomy | % of pipeline steps with no human; human minutes per week; first-pass approval rate | Graph step count; timed approval decisions | Each human touchpoint listed with its reason |

Extra rows when those phases exist: Laya escalation rate and agreement (§6.3), GEPA before → after (§8.1), video QA pass rate, L1 determinism pass (§7.5), open-vs-paid preference (§7.7), arm leakage with and without the D1 check (§9).

---

## 17. Requirement IDs (cite these in docstrings and tests)

| ID | Requirement |
|---|---|
| FR-01 | Brand constitution generated from the brief, human-edited, frozen and versioned |
| FR-02 | Content strategy: segments, pillar mix, cadence, posting windows (Africa/Cairo) |
| FR-03 | Weekly calendar of slots (date, time, format, pillar, segment, hook) |
| FR-04 | EN and AR captions composed natively from one shared brief |
| FR-05 | Hashtags selected by code from the tiered bank (8–15, ≥ 1 branded, ≤ 30) |
| FR-06 | At least one reel concept per week: hook, shot list, EN/AR overlays, audio, CTA, cover |
| FR-07 | Media attached and validated (JPEG, 4:5–1.91:1, ≤ 8 MB, sRGB; reels per §11) |
| FR-08 | Check cascade: rules → System-1 → judge; one revision; flag to human |
| FR-09 | Human approval queue; nothing publishes without APPROVED/EDITED |
| FR-10 | Publish via adapter (dry-run/live), 3-step flow, publishing-limit check, idempotent |
| FR-11 | Ingest engagement metrics per post and reel |
| FR-12 | Seeded engagement simulator for dry-run |
| FR-13 | Optimizer updates beliefs and changes the next plan inside brand limits |
| FR-14 | Benchmark harness computes all metrics (§16) with one command |
| NFR-01 | Cost per post < $0.01 on free/low-cost models (report actual) |
| NFR-02 | Latency per post (generate + check + revise) < 30 s p50 |
| NFR-03 | Reproducibility: seeds, pinned models, cached LLM calls, `uv.lock` |
| NFR-04 | Safety: no auto-publish; secrets never logged |
| NFR-05 | Swappable LLM, decision engine, image/video backends and publisher via config |
| NFR-06 | Every LLM call and render logged with model, tokens, latency, cost |
| NFR-07 | Tests run offline in CI |
| NFR-08 | RTL-safe Arabic rendering in text and on media |
