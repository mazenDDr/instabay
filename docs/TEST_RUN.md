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
make vision-up      # gpu-box: d3-flash, Qwen3.5-9B judge + writer, FLUX.2-klein; opens a tunnel
make studio         # http://127.0.0.1:8780 (shows runs under outputs/studio/)
```

`make vision-up` runs these by hand:

- `ssh gpu-box`, then start `uvicorn gpu_worker.vision_server:app` in tmux `instabay-vision`;
- open the tunnel with `ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 gpu-box`.

Only one model sits on the GPU at a time. Switching between sorting, the judge and camera views
reloads a model (4–15 s). The first request after a switch is slower.

## 3. In the dashboard

1. **Settings**: enter your name. It is stored with every freeze and approval.
2. **Home**: set posts per week, reels and carousels, then **Save mix**.
3. Choose a mode:
   - **Autopilot**: open **Media → + Add photos**, drop the photos, tick *Autopilot* and
     **Upload**. Everything runs: sorting into pillars, planning, new AI shots where a pillar
     is short, then writing the English and Arabic posts. It stops at your approval.
   - **Step by step**: upload photos, then click **Prepare week** (top right) → *Step by step*.
     It pauses after sorting, after planning and after the new shots. Look at Media or Planner,
     fix pillars and approve the new shots you like, then click **Continue**.
4. **Content**: approve or reject each post. Posts with review notes need a reason.

How it decides:

- The **writer** (Qwen3.5-9B) sees the photos themselves. Descriptions are optional. If you write
  one, it is used as a fact; otherwise the writer notes what it sees, in English and Arabic.
- **No photo is used twice in a week**, and a post never shows the same spot twice (a photo and
  any AI shot made from it count as one spot).
- When a post lacks photos of its pillar, **FLUX.2-klein makes a new shot** from one or two of
  your photos of that pillar, using only what is in them. d3-flash scores each shot for
  *same place* and *photoreal*. Autopilot keeps shots that score at least 80% on both. Every
  post that uses one carries the AI disclosure in English and Arabic.
- Reels are written as concepts; rendering them as video is a separate step for now.

Photos under 1080 px (for example 545×545 downloads) are upscaled and flagged. Upload the original
files before going live.

## 4. Try Insights before Instagram (simulated)

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

## 5. Stop

```sh
make vision-down     # frees the GPU and closes the tunnel
```
