# Phase 6 decision layer

The default demo/cycle still uses the fixture judge. No real Laya/Jev model, calibration gold
set, speedup or accuracy result has been verified. Native adapters are opt-in and all automated
checks use synthetic answers, HTTP mocks or optional-module doubles.

## Engines and wire contract

`DecisionEngine.decide(state, questions)` returns typed Choice, Score or Noul answers.
`FakeDecisionEngine` accepts only exact state/question hashes and fails on unknown fixtures.
`SystemOneHTTPEngine` uses `POST /v1/systemone` for a configured laya-serve or hosted endpoint.
`LayaLocalEngine` imports Router lazily, requests CUDA, uses one resident model and requires
both English/multilingual checkpoint directories to exist locally. It never installs packages
or intentionally downloads weights. Missing packages, checkpoints or incompatible API shapes
produce an unavailable result and cascade escalation.

# HUMAN: run optional local inference only on gpu-box using its existing `main` environment.
The read-only Tailscale/SSH check passed; no GPU job was started. There is no spike ADR yet.
Inspect package/torch compatibility before installing a pinned Laya version; do not replace
the prepared CUDA 12.8 torch build. Record measurements in `docs/adr/0000-spikes.md`.

External inference requires `confirm_external=True` (local GPU: `confirm_gpu=True`) and
`INSTABAY_DECISIONS_ENABLED=1`. Hosted calls additionally read
`INSTABAY_SYSTEMONE_API_KEY` from ignored `.env`. Tokens stay in a bearer header, never request
bodies, URLs, serialized profiles or provider error messages. Hosted TypeSafe models must be
explicitly version-pinned. Model/server revision is part of engine identity; change it after
any deployment/checkpoint change and revalidate calibration. Local HTTP is limited to the
configured Tailscale address/alias or loopback; hosted credentials are refused over local HTTP.

Provider confidence is **not** treated as domain calibration. TypeSafe's Noul wire format has
only P(yes); absent confidence is normalized to `max(p, 1-p)`. Laya can supply a separate
confidence. Choice/Score use the supplied confidence; Laya's entropy confidence and Jev's
confidence need separate engine-scoped fits. Provider abstention is preserved. Unsupported
IDs, primitive types, choices, probabilities and ordinal ranges fail closed. Extra provider
metadata is ignored rather than logged. Score uses the adapter's ordered 0-based levels;
verify this contract against the selected hosted model before a real call.

## Gold data and calibration

# HUMAN: record real D1/D2 predictions, independently label at least 300 unique items (at least
40% Arabic), and audit at least 60 items. Use a different model family for judge labels and
record that provenance with your research evidence. Do not relabel synthetic fixtures as real.
Predictions and independent labels enter `CalibrationData`:

```python
CalibrationData(
    engine_id=engine.engine_id,
    brand_hash=brand_hash,
    provenance="human_audited",  # HUMAN: real labels and recorded prediction provenance
    cases=[CalibrationCase(
        item_id="post-001-ar", group_id="post-001", language="ar",
        state_hash=canonical_hash({"state": state}),
        question_id="hook", question_hash=question.hash,
        answer=answer, gold="question",
        human_gold="question", human_actor="YOUR_NAME",
    ), ...],
)
```

The model rejects duplicate item/question rows, conflicting item identities and repeated
state hashes assigned to different groups. EN/AR counterparts share their group. Deterministic
60/20/20 **group** splits prioritize leakage prevention; unequal group sizes can produce
unequal item ratios. Train is reserved for future model fine-tuning. Only validation fits
per-question/per-language temperatures and abstention thresholds. Test never retunes them.

```sh
uv run --offline --no-sync instabay calibrate-decisions \
  --data outputs/decisions/labeled-predictions.json \
  --output outputs/decisions/calibration.json
```

There is no fabricated default label file. Missing or inadequate real labels stop calibration.
The dependency-free fitter scales **reported-confidence correctness logits**, not the model's
class logits, then maximizes validation coverage subject to observed 95% accepted precision.
It requires at least ten retained validation and ten retained test examples per active cell.
Held-out accepted precision below 95%, escalation at least 70%, absent language/question data
or no acceptable threshold disables that cell. Output includes accuracy, ECE before/after,
precision with a Wilson 95% interval, escalation and human agreement/Cohen's kappa by cell.
Degenerate/absent agreement stays null. Observed precision is not a guarantee of future accuracy;
inspect intervals and audit representativeness before deployment. Real runtime/cost savings
remain pending actual recordings and prices; synthetic timings are not a production result.

Profiles bind engine identity, brand hash, question hash (instructions and criteria), language
and dataset hash. Synthetic evidence can be used only by a synthetic engine with an explicit
test/demo allowance. It cannot enable a native fast path. Unknown/mismatched evidence escalates.
The kill criterion keeps poorly performing D2 cells on the judge route. D1 also requires its
own valid cells; it does not become trusted because D2 failed. Fine-tune on gpu-box only if
real Arabic results justify it, then refit on separate held-out data.

## Cascade and persistence

`WeekRunner` accepts optional `decision_engine` and `calibration` objects. Defaults remain
judge-only. Synthetic fast paths require a demo run and `allow_synthetic_decisions=True`.
The cascade checks deterministic rules first; rejected content does not reach System-1.
It asks atomic hook/pillar, sales-pressure, tone and register questions separately for EN/AR,
without exposing the planned arm as classifier input. All required calibrated checks must
meet their policies before skipping the judge.

Only uncertain/adverse question IDs enter escalation context. The existing three-sample
rubric still returns a full quality verdict; it does not fabricate independent resolved labels
for every atomic question. Dedicated EN/AR escalation prompts are Markdown. A reproducible
10% snapshot/seed sample sends accepted checks to the judge for audit. Its realized fraction
varies on small weeks. High confidence in an adverse answer also escalates. Failure gets at
most one bilingual revision, and revised text receives a new trace. Engine failure falls back
to the judge. Remaining failures/concept-only media are flagged for the human.

SQLite stores raw answers, question/engine/profile/content hashes, calibrated confidence,
escalation and audit outcomes. Unknown answers remain absent in the trace; raw provider
confidence is distinguished from calibrated confidence. A System-1-only review has no rubric
score or invented judge samples. Legacy reviews retain their three samples after an additive
nullable migration. Every route still reaches the persistent approval interrupt and publishing
still requires the latest exact stored APPROVED/EDITED decision. Calibration never approves.

`CalibratedFidelity` requires calibrated EN/AR hook/pillar consensus; disagreement or missing
proof stays unverified. A confirmed mismatch is logged as leaked. Scheduling/format facts are
kept separate from semantic evidence; no actual publication-time inference is claimed. Live
Graph reward normalization and bandit learning remain blocked pending a reviewed live path.
`InjectionGuard` supplies D3 for future untrusted comment/trend ingestion: uncertainty holds
text for review before prompt insertion. D4 learning from real approval logs and D5 live comment
triage remain dependent on human data and go-live integration; queue ordering is still FIFO.

## Source verification

Primary [TypeSafe introduction](https://docs.typesafe.ai/introduction) documents the three
primitives and Noul/Choice/Score distinction. Its generated API pages could not be accessed
consistently; hosted contract/version verification remains HUMAN work. Laya README,
`router.py`, `serve.py` and `calibrate.py` were read through the mazenDDr account at repository
revision `682ac6719faa5b1c04b529501feb93e58ee91f3d`:
[primary source](https://github.com/NandhaKishorM/laya/tree/682ac6719faa5b1c04b529501feb93e58ee91f3d).
Its calibration utilities consume native model records/logits and are not guessed or imported
by offline tests. The application-level scalar fitter is intentionally independent. Actual
optional-package/weights/Arabic quality checks await the Phase 0 spike.
