# Frozen audience v1

This simulator was committed before optimizer code. It imports no application code and
does not accept a policy. These are synthetic assumptions, not claims about resort marketing.

For each world seed, independent factor-level coefficients are Normal(0, 0.3). Reach is
LogNormal(7.3 + format/time effects, 0.35); reach effects are Normal(0, 0.15). Engagement
logit is -3 plus the four factor effects and Normal(0, 0.1) observation noise. A Binomial
draw gives total engaged accounts; sequential Binomial draws split them into likes,
comments, saves and shares with probabilities 0.75/0.07/0.12/0.06. Counts are exclusive,
so the reward is in [0, 1]. Views add a Binomial reach draw (0.3, or 0.6 for reels).
Reel watch-through is Beta with concentration 8 and sigmoid(hook coefficient) mean.

SHA-256-derived random streams key audience effects by seed/factor/level and observations
by seed/event ID. Retry and request order therefore do not change observations. Keep event
IDs shared across policies in later paired comparisons. Determinism targets pinned Python
3.12; a frozen JSON observation catches accidental drift. Benchmarks and oracle comparisons
belong to Phase 4; no performance result has been used to choose these constants.
