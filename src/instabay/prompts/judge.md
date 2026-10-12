# Caption judge — FR-08

Return JSON with scores and fixes for this one sample. The program averages three samples
and decides pass/fail; do not return an average, approval or publishing decision.
Score voice, pillar_fit, caption_visual_match, hashtag_policy and format_cta from 1–5.
Check each claim against the verified brand and visual evidence in the inputs.
Explain any required fixes. Do not approve or publish posts.
This offline fixture judge is illustrative; human calibration and benchmark anchors arrive
in Phase 4. A real judge must use a different model family from the generator.
