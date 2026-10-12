# Coastal week — real generation, unpublished review sample

Open the [mixed-format gallery](review/index.html). Watch [the stay-inspiration reel](reference-w42-wed-1/reel.mp4)
or [the travel-planning reel](reference-w42-sat-1/reel.mp4).
The gallery has **3 single photographs, 2 carousels (three and two images) and 2 scenic reels**, with
English and Arabic captions, actual album navigation and source links.

These are historical reference photographs of **Reethi Faru Resort, Maldives**, by Moosa
Haleem on Unsplash, published in April 2020. They do not represent fictional Insta Bay's
facilities, establish current resort conditions or imply an affiliation. The source images,
authors, licenses and modifications are in the [photo manifest](../../../assets/photos/reethi_faru/manifest.json).
Reels contain AI-generated motion, disclosed in both caption languages. No post is approved
or published.

Each film shows three distinct full scenes for five seconds each: visible villas and
water, shoreline, and a palm-lined jetty. There are no photographic zoom shots or blue
caption panels. Opening/body overlays are removed by the editor; small source credits close
the film. The continuous ambient soundtrack is synthesized from tones/noise, with no
licensed music or copied reference-video audio. The film is language-neutral; the captions
are independently composed in EN/AR.

## Inspect the actual evidence

- [Native campaign and pending reviews](campaign.native.json), including original recipe/runtime identities.
- [Review campaign](campaign.review.json), with portable CPU reassembly and explicit copy edits.
- [Raw requests and responses](native-calls/), including failed attempts.
- [Generation ledger](generation.json), with observed usage/statuses, not fixture statistics.
- [Verification evidence](verification.json), [Linux replay](linux-replay.json), [desktop gallery](gallery-desktop.png) and [phone gallery](gallery-mobile.png).
- [Caption runtime and pinned weight manifest](caption-runtime.json).
- [Copy revisions](editorial-revisions.json): only openings/actions were edited; source-compiled bodies and alt text remain unchanged. Raw copy is retained, and edits remain pending human review.
- [First experiment](campaign.first-experiment.json): repeated single-photo choices and repetitive framing are preserved, rather than hidden.
- [Stay-film measurements](reference-w42-wed-1/creative.json) and [planning-film measurements](reference-w42-sat-1/creative.json).

The caption experiment uses the pinned Qwen3-8B NF4 worker. The raw Arabic still needs
editing, and native openings can repeat. The gallery contains documented editorial
revisions, **not untouched LLM output**. The compiler binds visible factual clauses and
selected media; the model supplies framing. Source/format constraints block unsafe drafts,
while aesthetic defects remain available for review. The editor binds timing, text policy
and scene-order diversity; each reel's `direction-policy.json` records raw versus edited
orders and overlays. No viewer preference, retention increase or commercial effect has
been measured.

The three [motion folders](motion/) preserve original Wan recipes, results, clips and
first/middle/last frames. They were generated from three different source photographs at
576×1024/12fps, then interpolated to 30fps and upscaled to 1080×1920 for assembly. Each native
clip took roughly six minutes; no native 4K camera quality is claimed. The two films reuse
this small three-scene library across the week; within each film every scene is distinct.
`text_fraction` measures narrative overlays and excludes closing source credits.
Movement is gentle, and the near-static shoreline diagnostic remains visible. Inspect
actual playback and source geometry before deciding whether it is satisfying.

## Reassemble from the recorded clips

The native GPU recipes retain their original GPU-run paths. CPU assembly recipes reference
committed source clips, boards, derived crops, fonts and actual audio bytes. Result records
retain original local render paths as audit evidence; the linked MP4s are the viewable copies.
Frame hashes are stored as named entries in each `frames.json` manifest.

Create a recipe for your own runtime and reassemble without another GPU generation:

```sh
uv run python scripts/reassemble_scenic.py \
  --recipe docs/samples/coastal-week/reference-w42-wed-1/recipe.json \
  --output outputs/coastal-replay
```

Different FFmpeg builds can encode different JPEG bytes from the same crop. Replay retains
the stored conditioning images and verifies their original hashes instead of recreating them.
Original recipes intentionally reject changed implementation or FFmpeg bytes. Regenerating
the CPU recipe is distinct from regenerating native footage. The full direction and mixed
content design are documented in [CONTENT_DIRECTION.md](../../CONTENT_DIRECTION.md).

**Next review:** source fidelity, natural movement, pacing, soundtrack and EN/AR copy. For
customer-facing production, use current verified property media and approve the complete
post snapshot. The gallery's edited copy is a separate review snapshot; approving an older
native database row does not approve these edits.
