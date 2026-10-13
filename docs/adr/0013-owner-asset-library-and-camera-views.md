# ADR 0013: Owner photo library, d3-flash pillars and AI camera views

Date: 2026-10-13

## Context

The owner wants to give the workflow real resort photos, have each one sorted into a brand
pillar, let the planner pick photos per post/reel, set the weekly reels/posts mix, and create
new camera views of the real place (waterline, aerial, guests in frame) for more varied posts.
They asked for `vllm-sr/d3-flash` for this. d3-flash is a System One decision model: it
returns probabilities for choice/yes-no/score questions and never draws images.

## Decision

- **Library.** `instabay.assets.AssetLibrary` stores content-addressed photos under
  `data/workspace/assets` with a small SQLite file. Uploads need a rights/consent confirmation;
  EXIF (GPS, device) is stripped and its rotation applied.
- **Pillars by d3-flash.** `D3FlashHTTPEngine` sends the image and the brand's pillar
  descriptions to the existing `/v1/systemone` contract. Labels under 0.60 confidence wait for
  the owner. Owner corrections are stored as labels, and the dashboard shows agreement and
  Cohen's kappa, so the classifier is measured rather than trusted.
- **Planner.** The owner's posts/reels/carousels mix is a cadence override. The frozen brand
  and its hash are unchanged, and pillar limits are re-checked. Code ranks photos per slot
  (same pillar, least used, real before generated, then confidence). The visual brief writer
  may choose only from that pool. LLMs still write; code decides.
- **Camera views.** An image-edit model (candidate `FLUX.2-klein-4B`, Apache-2.0, fits 16 GB)
  re-shoots an owner photo from a preset direction. The prompt forbids added buildings or
  facilities. Every view stores its recipe and hash (rule 5). d3-flash then answers "same
  place?" and "photoreal?" on (original, view). No view is planned until the owner approves it.
- **Disclosure.** An approved view becomes `source: synthetic` with the new
  `approval_scope: owner_approved_view`. That lets it reach a live post, unlike reference
  material. Any photo/carousel that contains one carries `ai_disclosure=true` and the EN/AR
  disclosure line (rule 6). This is enforced in the `Post` validator.

## Consequences

- d3-flash weights are 16.8 GB in bf16, more than the card's free VRAM. The gpu-box service
  keeps the 2 GB token-embedding table in CPU RAM and the rest on the GPU, with no
  quantization, so the numerics are unchanged. It needs transformers 5.17. That is installed
  in an isolated `data/pydeps-d3` folder, so the shared `main` conda env is not changed.
- One large model is resident at a time; switching between classify and generate reloads.
- Pillar accuracy is unknown until the owner labels photos. The dashboard shows it and does
  not claim it.

## Measurements (gpu-box RTX 5060 Ti 16 GB, 2026-10-13)

| Step | Result |
|---|---|
| d3-flash load / VRAM | 13 s / 14.76 GB (embedding table on CPU, no quantization) |
| d3-flash, 1 photo, 2 questions | 1.7–3.2 s (median 2.5 s), 0/8 failures |
| d3-flash, 2 images (fidelity) | about 5.2 s |
| FLUX.2-klein-4B load | 3.7 s (model CPU offload) |
| FLUX view 2032x1360 / 1088x1632 | 32–39 s / 26–30 s, peak 9.97 GB |

12 views (6 presets × 2 photos) were judged by eye, by one rater (the agent), and compared
with min(d3 same_place, d3 photoreal):

| Group | Views | d3 min score |
|---|---|---|
| Looked right | 6 | 0.82–0.92 |
| Changed the place or looked fake | 5 | 0.45–0.72 |
| Borderline (invented rock in close detail) | 1 | 0.76 |

The dashboard flags views under 0.8 (`VIEW_OK`). The threshold comes from only 12 views and
one rater, so the owner still approves every view. Worst presets: `detail` (miniature look),
`aerial` from a ground photo (invents a site layout) and `golden_hour` on aerial water.
Best: `over_shoulder`, `golden_hour` on ground photos, and `guests`. The sample photos come
from two different resorts and were used only for this test.

## Addendum (2026-10-13): VLM judge, visual pillar wording, owner GUI

- **VLM judge.** When d3's top pillar is under 0.5, `Qwen/Qwen3.5-4B` (bf16, 9.1 GB, loads
  in 9.3 s) looks at the photo and returns one pillar plus a one-sentence reason. Its label is
  stored apart from d3's and the owner's (`vlm_pillar`), and each is measured separately
  against owner corrections. d3 runs over all photos first and the judge afterwards, so the GPU
  swaps models once.
- **Pillar wording matters more than the model.** On the owner's 13 Red Sea photos (545×545):

  | Pillar descriptions | d3 median top probability | photos ≥ 0.5 | plausible by eye (1 rater) |
  |---|---|---|---|
  | abstract demo wording | 0.51 | 7/13 | about 3/13 (almost all "setting") |
  | visual wording (template) | 0.76 | 11/13 | about 10/13 |

  The VLM answered 13/13, in 2–5 s each, and agreed with d3 on 10/13. Of the 3 disagreements,
  d3 was right on 1 (suite interior), the VLM on 1 (night restaurant), and 1 is ambiguous. Both
  put the beach photo under relaxation. The cascade sorted all 13 photos in 28 s (2 sent to the
  judge). The template `config/insta-bay-brand.example.yaml` uses the visual wording.
- **Low-resolution photos** (short side ≥ 400 px) are upscaled to the 1080×1350 feed and
  flagged at review: "use the original photo file before posting".
- **Owner GUI** is laid out like Meta Business Suite (Home, Content, Planner, Insights, Media,
  Settings). Approve/Reject in Content stores the same hash-bound approval as the CLI, and
  flagged posts need a reason. Insights labels simulator numbers as *Simulated*. Publishing stays
  a terminal step.

## Addendum (2026-10-13): multimodal writer, new shots, autopilot

- **Multimodal writer.** `Qwen/Qwen3.5-9B` in NF4 (pinned c2022362; 7.9 GB, 8.3 s load) now
  sees the photos. It serves the pillar judge, the visual brief and both caption languages from
  the one gpu-box service. For photos without owner descriptions, the brief writer adds EN/AR
  observations, which become the facts. Prefilling the reply with the object's first key fixed
  schema echoing (0/2 → valid). Speed: brief ≈46 s, each caption ≈17 s, ≈6 min for a 7-post week.
- **Uniqueness.** Pools are reserved per post. On the real week: 0/7 posts had two images of one
  spot, and 14 distinct images filled 16 places; the 2 repeats were the last resort with 13
  photos + 1 shot.
- **New shots (FLUX.2-klein, multi-reference).** In the first real run 8 shots were made: a pillar
  with no photos got an invented infinity pool, and single-source shots were near-copies (dHash
  ≈30/256 vs ≥92 between distinct photos). Policy now: no shots for photo-less pillars (reported
  to the owner), drop near-copies (< 64), keep when d3 same-place ≥ 0.8. d3 photoreal rated
  clearly real shots 0.45–0.59, so it is shown but not used to decide. Second run: 8 shots, 1
  kept — a new photo of guests dining at the same rooftop bar, with no invented elements.
- **Modes.** Autopilot ran the whole week to approval on the owner's photos in 499 s (resumed
  after the fixes). Step by step pauses after sort, plan and shots (tested offline).
- **Known weak spot:** the Arabic from the 9B NF4 writer has word errors ("بركة" for pool,
  invented words). Every post stays flagged for human review; a 4B-bf16 vs 9B-NF4 writer
  comparison is the next measurement.

## Addendum (2026-10-13): reasons only for rejections; feedback memory

- **Owner decision:** approving a post, even one with review notes, needs no reason. Rejecting
  still requires one. The notes stay visible in the drawer, and the approval is the owner's
  statement.
- **Feedback memory, not fine-tuning:** the latest decision per post is read from every run
  database. Rejection reasons become `owner_feedback.avoid` for the brief writer and both caption
  writers. Caption edits (from the stored EDITED diffs) become `owner_feedback.prefer`, per
  language. At most 8 notes per list, newest first. An undone rejection (REVOKED) is not a lesson.
  The owner can **Forget** single notes or bring them all back in Settings. No weights change.
  When there are no notes, the inputs are unchanged, so earlier cache keys and recordings still
  apply.
