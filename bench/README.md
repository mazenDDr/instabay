# Benchmark protocol

`make bench` runs offline with FakeLLM and writes all five required metric blocks to
`bench/results.json`, then regenerates the marked README table. It does not create an
approval or publish any post. Human scores/times and unavailable prices remain null.
The corpus and all scores are fixture examples, not real model performance.

## Fixed inputs and evidence

- `corpus.json`: 21 frozen slots, three seven-post weeks, brand hash and content signatures.
- `fixtures/llm/`: 21 Arabic evaluator cases and 10 generic-caption rubric cases. The core
  shared briefs and rubric responses come from the explicit cycle catalog; 21 distinct
  native EN/AR caption pairs have benchmark-only overrides. Every judge uses three
  requests at temperature zero. FakeLLM supplies all responses; no real independent model
  family is exercised. Real runs must use a judge from a different generator family.
- `fixtures/negative_controls.json`: ten distinct generic EN/AR captions, paired with the
  first ten corpus posts. The canned score difference is a harness sanity check.
- `fixtures/translations.json`: twenty **authored literal-translation fixtures**. They
  have not been recorded from an MT provider. All 20 native and 20 comparison captions
  in the blind packet are distinct. Do not claim general Arabic quality from this pack.
- `rubric.md`: written anchors for the five brand dimensions and three Arabic dimensions.

Intermediate posts, three judge samples, deterministic rules and cold call metadata are
written to `outputs/bench/content.json` and `calls.jsonl`. Complete optimization seeds,
including every policy/week planned arm, executed arm and outcome, are flushed to
`seed-checkpoints.jsonl`. A code/data/Python fingerprint prevents stale cache reuse.
An interrupted trailing record is recomputed. Latencies and UTC timestamps vary by run;
seeded optimization results are deterministic. No simulator or optimizer code was tuned
after inspecting this protocol's results.

## Definitions

Brand consistency averages the five rubric scores over three samples and 21 posts. Hard
rules are reported separately. Calibration takes 20 human-labeled posts and reports
quadratic-weighted Cohen's kappa on pooled post/dimension pairs after averaging raters
and samples and rounding halves upward. No kappa is invented when labels are absent.

Arabic quality averages fluency, naturalness and brand voice. The blind packet mixes
20 native and 20 comparison captions. Ratings yield a mean and post-level interval for
each version, paired native win rate (ties count one half), interval Krippendorff alpha
over quality means across raters, and tied-rank Spearman correlation with judge means.
Single-rater items cannot estimate alpha; constant scores cannot estimate correlation.
These undefined values stay null. Partial coverage is marked partial, not complete.

Optimization uses **12 weeks × 7 posts × 20 independent world seeds (0–19)**. Fixed repeats
each seed's initial Thompson plan; uniform samples feasible pillar sequences and formats
without using reward knowledge; Thompson uses the existing factored Beta update; oracle
uses privileged frozen logits only inside the benchmark. The declared weekly plan family
has common preferred hook/window for six posts and alternate hook/window for the first
exploration post, arbitrary pillar order, and per-post formats with the minimum reels.
The oracle optimizes exactly within that family, with all brand bounds and windows.
Expected reward integrates logit noise by Simpson quadrature; cumulative regret is the
sum of oracle expected rate minus executed expected rate, in rate-sum units, not money.

Late-period rate is the mean post engagement rate within weeks 9–12, then the mean across
worlds. Uplift is the ratio of Thompson/fixed world means minus one. The 95% percentile
bootstrap resamples paired whole world seeds, **2,000 resamples with bootstrap seed 42**.
Posts in a world are never treated as independent seeds. A separate predeclared 20%
week-level hook-rotation experiment preserves constraints and compares unguarded updates
with an ideal synthetic D1 guard. Guarded-minus-unguarded regret is paired; an interval
crossing zero does not establish an effect. This does not measure a real D1 engine.

Efficiency separates 18 feed posts and three reel concepts, uncached ledger tokens/spend,
local cold end-to-end wall p50/p95, provider latency sums, brand setup and benchmark-only
evaluation overhead. Fixture token counts are illustrative and actual spend is zero.
No video is rendered, so no render cost/latency is claimed. Paid list-price estimates are
null unless model-specific price cards are supplied. Cached responses are not charged.

Autonomy lists eight configured weekly stages: brand, plan, draft, checks, human approval,
publish, metrics, learn. Seven are configured automatic (87.5% topology share). This
content-only benchmark completes four automatic stages and stops before approval.
Operational autonomy stays null; topology is not a measured full-loop success rate.
Returned first-pass feedback yields human minutes per week, approval rate and every
touchpoint/reason. Feedback never grants application publishing authorization.

## HUMAN inputs

1. Run `make bench`. It prints the corpus-specific packet directory under
   `outputs/bench/human_packet/CORPUS_ID/`. Give raters `arabic_blind_items.json` there and
   a copy of `arabic_template.csv`. Keep `arabic_key_private.json` away from raters.
   Fill one CSV per Arabic rater (two or more to estimate agreement); use opaque item IDs.
2. Give brand raters the first 20 posts in `content.json`, this rubric and
   `brand_template.csv`. Record all five dimensions and a rater ID. The template's
   `content_signature` must be retained to bind ratings to the exact post.
3. Fill `approval_template.csv` with first-pass decisions, seconds and reasons. These are
   measurements only. Use `instabay approve` separately for actual publishing approvals.
4. Save completed CSVs as `bench/human_ratings/brand_NAME.csv`, `arabic_NAME.csv` and
   `approval_NAME.csv`, or pass a private directory with `instabay bench --ratings PATH`.
   They are git-ignored. Existing templates are preserved on repeated runs, and a changed
   corpus gets a separate packet directory. Blank scores
   stay pending; partially filled, duplicate, out-of-range and stale rows fail clearly.
5. # HUMAN: record real MT to replace authored comparisons before a real language claim.
   A `recorded_mt` case must include its model, UTC `recorded_at` and `english_source_hash`
   (SHA-256 of the exact EN caption). Changing captions invalidates old rating signatures.
   Native fixture results still do not stand in for a real generator benchmark.
6. # HUMAN: provide verified model prices for real providers with `--prices PATH`. The JSON
   list schema is `[ {"model": "MODEL_ID", "input_usd_per_million": 0.0,
   "output_usd_per_million": 0.0, "source": "OFFICIAL_PRICE_PAGE", "verified_on": "YYYY-MM-DD"} ]`.
   Those zeros illustrate the schema, not a price claim. Missing models keep paid cost null.

`instabay bench --output PATH --artifacts PATH --ratings PATH --readme PATH` selects paths.
The README must contain exactly one `<!-- BENCHMARK:START -->` / `<!-- BENCHMARK:END -->`
pair. Text outside it is preserved. A manual GitHub `bench.yml` workflow runs the same
offline protocol and uploads results; it does not commit them or access paid services.

See [ADR 0004](../docs/adr/0004-benchmark-protocol.md) for the decisions and limitations.
