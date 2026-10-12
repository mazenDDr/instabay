# Phase 4 report

## 1. Built

`src/instabay/benchmarks/` implements schemas, statistical summaries, constrained policy
comparisons, the privileged benchmark-only oracle, fixed content replay, human CSV ingestion,
ledger efficiency and README generation. `bench/` holds corpus v2 (21 distinct EN/AR caption
pairs), 20 distinct authored comparison texts, 10 distinct generic negative controls,
rubric anchors, human-input instructions and results. The `arabic_judge.md` prompt is in
Arabic. CLI/Makefile/Docker support `bench`; a manual offline GitHub workflow uploads evidence.

## 2. Gate evidence

| Check | Observed result |
|---|---|
| `make setup test lint` / final `make lint test` | 103 offline tests passed; Ruff clean; strict mypy clean in 46 source files |
| `make bench` | Wrote all five metric blocks to `bench/results.json` and regenerated the README table |
| Quality corpus | 21 distinct EN/AR pairs; 40 distinct blinded texts; 3 samples per judge; 10 distinct controls |
| Policy protocol | 12 weeks × 7 posts × 20 seeds; 4 core policies plus 2 synthetic leakage variants; 10,080 observations |
| Seed uncertainty | 2,000 paired whole-world bootstrap resamples; exact replay and fixed-vs-Thompson week-1 pairing tested |
| Oracle and constraints | Known reel opportunity-cost result and dominance over random/production plans tested |
| Human input paths | Synthetic test CSVs exercised kappa, native/MT means, win rate, alpha, correlation and timed feedback |
| Failure handling | Partial/stale/duplicate ratings fail; truncated checkpoints recover; filled templates survive reruns |
| Safety | Tests forbid benchmark approval/publisher calls; live environment rejected; no real queue changed |
| Pinned Docker | Built and ran as UID 10001 with networking disabled; all metrics generated without an approval DB or outbox |
| Preservation | Simulator, optimizer, SPEC, cycle catalog and original resort photos unchanged from main |

The committed `bench/results.json` is the source of the README numbers. The first corpus
audit found only five unique reused captions. Benchmark-only text overrides replaced them;
corpus v2 and corpus-specific packet directories prevent stale rating reuse. The synthetic
policy outcomes are identical before and after this content correction.

Results describe **only the frozen synthetic world**:

| Comparison | Mean | Paired 95% interval |
|---|---:|---:|
| Thompson vs fixed week-1 relative uplift, weeks 9–12 | 68.20% | 37.77%–114.14% |
| Synthetic D1-on minus D1-off cumulative regret | +0.0832 | −0.0390 to +0.2141 |

The leakage guard does not establish a benefit here; its interval includes zero. This
result was retained without tuning. Canned brand score is 4.60/5, control 2.20/5 and Arabic
judge 4.67/5. Those constants test the harness and are not independent quality evidence.
Real ratings, judge agreement, Arabic preference, human time and paid-provider prices
are missing, so those corresponding fields remain null. Feed/reel-concept usage and local
timing are measured from fixture ledgers; no real LLM latency or video rendering is claimed.

## 3. Deviations and ADR

[ADR 0004](adr/0004-benchmark-protocol.md) fixes the measurement protocol, the constrained
weekly oracle family, ideal synthetic D1 ablation and missing-data handling. The five metric
rows exist even where human-only evidence is pending. Actual model-family independence and
real MT quality await recordings. Autonomy separates the configured 87.5% topology share
from unavailable full-loop operational measurement; the benchmark never fabricates approval
or publishing events. Public SHA-256 metadata has a narrow secret-scan line exemption; all
other benchmark text remains scanned.

## 4. HUMAN items

- # HUMAN: review and merge the Phase 4 PR.
- # HUMAN: use the printed `outputs/bench/human_packet/CORPUS_ID/` directory to collect
  20 brand labels, 40 blind Arabic items from two or more raters, and timed first-pass feedback.
- # HUMAN: record real independent-model/MT cassettes and provide verified real-provider
  price cards before interpreting quality/cost as production measurements.
- # HUMAN: approve normal marketing drafts separately through the application queue.
  Benchmark feedback cannot authorize publishing. No GPU/model/Meta work was started.

## 5. Proposed next step

After merge and explicit continuation, Phase 5 adds the Instagram Graph publisher/insights
adapters and offline contract fixtures for FINISHED, ERROR, EXPIRED, rate limits and
idempotent retry. Stop at this gate until the human authorizes the next phase.
