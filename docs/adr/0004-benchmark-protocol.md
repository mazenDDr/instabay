# Phase 4: benchmark protocol and missing human evidence

Before the full results run, fix the protocol to 12 weeks, 7 posts, world seeds 0–19,
and 2,000 percentile bootstrap resamples. Compare per-seed mean post engagement rates in
weeks 9–12; uplift is ratio of policy means minus one. Resample the same world indices
together, retaining correlated posts/weeks inside each world. The fixed policy repeats
that world's Thompson week-1 plan. Uniform random draws feasible pillar sequences with
multinomial weights, reel-constrained format assignments, a weekly hook/window and an
alternate first exploration slot. The constrained oracle enumerates feasible mixes,
first-slot pillars, preferred/alternate hooks and windows, then allocates required reels
by opportunity cost. It optimizes this declared weekly family, not every conceivable
calendar. Expected rewards integrate the frozen audience's logit noise by Simpson
quadrature. Regret is oracle minus executed expected reward, summed over posts. Only this
benchmark-only oracle reads hidden logits; the simulator and optimizer remain unchanged.

Declare a separate synthetic 20% week-level hook-rotation experiment. Rotating all hooks
preserves the weekly family and exploration constraint. The guarded variant uses ideal
synthetic D1 labels and skips drifted observations; the unguarded variant attributes them
to planned arms. Paired seed intervals report the effect, including a null or adverse
result. No real D1 accuracy is inferred. Complete seed evidence is flushed incrementally
and resumed only under a code/data/Python protocol fingerprint; no tuning on these seeds.

The fixed 21-post quality corpus reuses the explicit canned cycle cases. Three fixture
judge samples and ten generic negative controls test scoring/reporting wiring, not real
model quality. Their repeated scores/captions do not establish statistical independence
or grader calibration. Brand QWK pools anchored 1–5 post/dimension pairs after human-rater
and judge-sample averaging with half-up rounding. Arabic packets shuffle twenty native
captions and twenty explicitly authored literal-translation fixtures. Human mean scores,
tie-half native win rates, interval Krippendorff alpha over the three-dimension mean and
tied Spearman correlation are calculated only from returned ratings bound to exact text.
# HUMAN: supply brand/Arabic ratings, and replace authored translation fixtures with
recorded real MT before claiming real native-versus-MT quality. Missing inputs remain null.

Per-post efficiency sums uncached pipeline ledger usage and measures cold local wall time.
Brand setup and benchmark-only evaluation overhead remain separate. Actual fixture spend
is zero; fixture token counts and local timing are not real-provider measurements. Paid
list-price estimates need explicitly attributed model price cards; absent prices are null.
Reels are concepts with no render job. Autonomy reports configured 7-of-8 automatic graph
steps separately from operational measurement. The content-only benchmark stops before
approval, never inserts approvals or publishes. Human timing feedback is analysis data,
not authorization. Full operational autonomy remains unavailable until the full workflow
is observed. This follows the safety rule even though the five benchmark rows include
pending HUMAN values. No human ratings, approvals, calibration or prices are fabricated.

The offline secret hook exempts only exact JSON lines for public SHA-256 signatures and
brand/corpus/protocol hashes. Those values are reproduced from the corresponding frozen
inputs/code. Credential fields and all other benchmark text remain scanned; no complete
benchmark file is excluded.
