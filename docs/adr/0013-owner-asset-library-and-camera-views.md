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
