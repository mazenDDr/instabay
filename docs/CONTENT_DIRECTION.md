# Place-led content and a mixed account

The creative objective is to make a viewer understand and want to explore a real place: water beside buildings, a readable shore, and palms in their setting. A complete scene provides the opening payoff. Small isolated crops and compulsory rapid cuts previously concealed that setting. Scenic direction now holds three to five distinct scenes for four to seven seconds each. Reference-week films have no caption panels; captions live with the posts. Generated physical footage, restrained interpolation and a continuous synthesized ambient score replace photographic zoom edits.

## What the supplied reference establishes

The [supplied video](https://www.youtube.com/watch?v=wjYZ0LgzK10) is *Caribbean Beaches Aerial Journey in 4K | Chill Island Vibes*, by Alejandro Torres. Its public metadata reports about 4 hours 43 minutes. Sampled public storyboard grids from its opening and a later interval show turquoise coasts, white sand, palms and buildings in spatial context, with repeated scenic views. These are visual composition references. We did not view the entire film or measure its continuous motion, audience retention or sales. None of its footage or soundtrack is used here.

Three complete photographs by Moosa Haleem depict **one property**, Reethi Faru Resort, Maldives:

- [Lagoon villas and island shoreline](https://unsplash.com/photos/aerial-view-of-green-trees-and-body-of-water-u94aG1t4xPE)
- [Beach, palms and existing thatched structures](https://unsplash.com/photos/palm-trees-on-beach-shore-during-daytime-BcqbKBVZ-Zk)
- [Palm-lined sand and wooden jetty](https://unsplash.com/photos/palm-trees-on-beach-shore-during-daytime-2opFBNXAJzw)

The photographer identifies this property; other photographs identified as Meeru were excluded. These images were published in April 2020 under the [Unsplash License](https://unsplash.com/license). The retained 3000px derivatives preserve the full source composition. Scenic conditioning crops must retain boxed place features and enough source pixels; feed photographs use the whole source on a neutral 1080×1350 canvas. The sources do not establish current resort conditions, availability, prices, guest experiences or affiliation with Insta Bay.

## Brief → evidence → content

The visual brief selects ordered source scenes and explains their connection to the pillar. Format-specific schemas require one image for a photo, at least two for a carousel, and at least three distinct scenes for a scenic reel. Code binds the source facts for those images. EN and AR writers work independently on an opening and action. The caption body and alt text are compiled from localized factual clauses, rather than allowing the writer to invent sensory conditions or reinterpret buildings. Raw LLM requests and responses are retained alongside the resulting post; the published copy is therefore explicitly **model framing plus compiled evidence**, not untouched model output.

The sample's underwater pillar concerns visible water colors, not unseen marine life; relaxation concerns shade and space, not an invented spa; guest inspiration contains no fake testimonial; travel planning contains no fabricated offer. These are separate reference-campaign descriptions. The frozen `config/brand.yaml` remains unchanged.

Minimum format counts belong to the cadence configuration. The reference week has three single photographs, two three-image carousels and two reels. Existing configurations default the new photo/carousel floors to zero, preserving their previous planner behavior. Every media artifact, selected source, factual clause and caption participates in the post approval snapshot.

## Real generation and limits

The three scenic clips were generated on gpu-box through Tailscale using the existing pinned Wan 2.2 TI2V 5B installation: 576×1024, 61 frames at 12fps, 40 steps, CFG5, shift3, seeds2500–2502. Each clip took roughly six minutes of inference. FFmpeg interpolates the selected scene intervals to 30fps before social-resolution upscaling. This is **not native 4K camera footage**. All three raw motion recipes/results and source clips remain available for inspection. The two reels reuse this three-scene library in different editorial orders; each individual film uses distinct scenes.

The caption worker uses pinned [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B), NF4 quantization and disabled thinking, with hashed local weights. A one-case paired check corrected a viewpoint error from the smaller writer but still produced an inaccurate relation between shadows and sky. Typed scene binding and factual compilation address this observed failure; no general model quality win is claimed. Model weights remain on the GPU PC. Only `yt-dlp` was added to its environment for reference research; Torch and the existing inference stack were retained. A dedicated keepalive SSH tunnel avoids the observed idle ControlPersist tunnel closure.

Motion QA records normalized grayscale differences and near-static fractions. Sky and sand occupy much of these scenes, and shoreline motion is subtle; existing nearly-static flags remain visible. Human review must judge whether the actual movement, source fidelity and pacing are satisfying. Technical validity and source grounding cannot establish audience appeal or engagement uplift.

## Run and review

Offline mixed draft, with real feed images and fixture copy:

```sh
uv run instabay reference-week --output outputs/reference-week
```

Explicit offline animatic, useful for timing but not a finished physical-motion reel:

```sh
uv run instabay reference-week --output outputs/reference-animatic --render-reels --animatic
```

Real drafting requires the explicitly enabled caption worker and a dedicated Tailscale/SSH tunnel. Pass its pinned model ID with `--confirm-generation`, and pass a source-identical `--scenes` catalog containing verified motion clips. The CLI records requests/responses, persists checkpoints, renders media, exports a local review gallery, and stops at `approval_pending`. It requires dry-run mode. Failed calls remain in the ledger; resuming does not conceal them. Fixtures cover the supplied reference week, not arbitrary future campaign IDs.

The gallery supports format filters, actual carousel navigation, video playback and EN/AR caption switching. Reels without language-specific panels use the same film with independently written captions. No automatic beauty judge is used, and no human score is invented. Reference source authorization is distinct from crop or post approval. Reference artifacts cannot be made live by supplying a differently labeled upload manifest.

**Human next step:** compare the new samples with the rejected previews, inspect buildings/jetty/palms throughout playback, and rate movement, pacing and copy. For customer-facing production, replace historical reference imagery with current verified property media and approve the complete post snapshot. No sample is approved or published.

The real sample retains two experiments. The first reused its aerial photo for every single
post and repeated many openings. The revised brief restricts single-photo reuse until the
available scenes have been covered, and each writer receives its own previous openings.
The scenic editor rotates an identical second-film scene order and recomputes shot roles;
this is a recorded deterministic editorial policy, not new generated footage. Source and
format defects block generation. Repetitive or awkward copy stays visible for human review:
a measured retry repeated its English opening, so aesthetic defects are flagged rather
than preventing the entire draft week from being inspected. The sample includes explicit
EN/AR opening/action edits, with original bodies, alt text and raw calls retained. These
edits are not human ratings or publication approval.
