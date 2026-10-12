# Owner test run

This guide runs the whole loop yourself: photos → pillars → weekly mix → plan → generated
week → your approval → insights. Everything stays in dry-run mode. Nothing reaches Instagram
until you add your key and publish on purpose ([GO_LIVE.md](GO_LIVE.md)).

You need the Mac (this repository) and gpu-box switched on with Tailscale running.

## 1. Brand (once)

The pillar descriptions are what the image models read when they sort your photos, so write
what each pillar *looks like*. On 13 Red Sea resort photos, d3-flash was confident on 11 with
the visual wording in the template, against 7 with the older abstract wording. See ADR 0013.

```sh
cp config/insta-bay-brand.example.yaml config/brand.yaml
# Edit config/brand.yaml: positioning, voice, pillars, hashtags, verified facilities.
```

## 2. Start the image models and the dashboard

```sh
make vision-up      # gpu-box: d3-flash, Qwen3.5-9B judge, FLUX.2-klein views; opens a tunnel
make studio         # http://127.0.0.1:8780 (shows runs under outputs/studio/)
```

`make vision-up` runs these by hand:

- `ssh gpu-box`, then start `uvicorn gpu_worker.vision_server:app` in tmux `instabay-vision`;
- open the tunnel with `ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 gpu-box`.

Only one model sits on the GPU at a time. Switching between sorting, the judge and camera views
reloads a model (4–15 s). The first request after a switch is slower.

## 3. In the dashboard

1. **Settings**: enter your name. It is stored with every approval.
2. **Media → + Add photos**: drop the resort photos and confirm you own them.
3. **Media → Sort into pillars**: d3-flash labels each photo (about 3 s each). When d3's top
   pillar is under 50%, the Qwen3.5-9B judge looks at the photo and picks one with a short reason.
   The tile shows *by d3 · 76%* or *by VLM*.
4. Open each photo:
   - fix the pillar if it is wrong; your corrections measure both models in **Settings**;
   - add a one-line English and Arabic description of what is visible; the captions are
     built only from these.
5. Optional: **Create view** on a photo for an AI camera angle (about 40 s). Approve only views
   that still show the real place. Views scored under 80% are marked *Check place*.
6. **Home**: set posts per week, reels and carousels, then **Save mix**.
7. **Planner**: check the week. Each day shows the photos the planner suggests.

Photos under 1080 px (for example 545×545 downloads) work for testing but are upscaled and
flagged. Upload the original files before going live.

## 4. Generate a week (terminal)

The caption model needs the GPU, so stop the image models first:

```sh
make vision-down
.tools/bin/uv run instabay brand-freeze --brand config/brand.yaml \
  --db outputs/studio/test-run/posts.sqlite --actor "YOUR NAME"
```

Start the caption service and its tunnel as in
[PRODUCTION_GENERATION.md §2](PRODUCTION_GENERATION.md#2-start-the-private-caption-service).
Then run:

```sh
INSTABAY_LLM_ENABLED=1 .tools/bin/uv run instabay generate \
  --brand config/brand.yaml --assets data/workspace --draft-only \
  --model 'Qwen/Qwen3-8B:nf4@b968826d9c46dd6066d109eabc6255188de91218' \
  --run-id test-w1 --week-start 2026-10-19 \
  --output outputs/studio/test-run --confirm-generation
```

`--draft-only` makes the photo and carousel posts plus reel concepts. Finished reels first need
`instabay animate-photos --scenes data/workspace/export/objects.yaml` (about 7 minutes per photo
on gpu-box).

## 5. Approve

Open **Content** in the dashboard and pick the run `test-w1`. Click a post to see both captions,
the media and the review notes, then **Approve** or **Reject**. Posts with review notes need a
reason. Each decision is stored against that exact content. If the caption changes, the
approval no longer applies.

## 6. Try Insights before Instagram (simulated)

Real Insights need published Instagram posts. To see the screens working now, run the offline
simulator. It uses canned captions; the numbers come from an audience simulator and are labeled
**Simulated**:

```sh
.tools/bin/uv run instabay cycle --weeks 3 --db outputs/studio/sim-insights/posts.sqlite \
  --checkpoints outputs/studio/sim-insights/checkpoints.sqlite --outbox outputs/studio/sim-insights/outbox
```

The cycle stops each week for you:

1. Approve that week's posts in **Content** (run `cycle-w01`, then `cycle-w02`, and so on).
2. Run the same command again. It exports, records the simulated results and drafts the next
   week.

After three weeks, **Insights** shows reach by week, engagement by format and pillar, and the
top posts.

## 7. Stop

```sh
make vision-down     # frees the GPU and closes the tunnel
```
