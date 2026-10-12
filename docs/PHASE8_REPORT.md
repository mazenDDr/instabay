# Phase 8 report

## 1. Built

- `ARCHITECTURE.md`: actual weekly/cycle flow, protocols, SQLite/hash/approval boundaries,
  native retry uncertainty and measured render scope, with two diagrams.
- `RESEARCH.md`: primary paper/docs evidence linked to implementation decisions and explicit
  limits; no vendor score or synthetic experiment relabeled as a real campaign result.
- `GO_LIVE.md`: offline reproduction, missing engineering, human brand/data/media/worker/account
  preparation, intentional native commands and safe uncertainty/recovery handling.
- README navigation/status, refreshed remaining-work backlog, ADR index and ADR 0008.
- `Dockerfile.validation` and its input exclusions, `make verify-clone`, clone-state evidence
  scripts and a separate CI clone gate. Runtime Docker image remains distinct from validation.

## 2. Gate evidence

Final local fresh-clone, Docker and CI results are added after execution. The gate runs the exact
`make setup demo test lint` sequence under UID 10001 with Docker networking disabled, then checks
that the default demo has a persistent approval interrupt, seven drafts and zero approvals,
publications, metrics, posteriors or render jobs; no outbox. All repository hooks run afterward.
The ordinary offline suite remains 252 tests; no new feature code or synthetic benchmark rewrite
is part of this phase. Machine-readable evidence is written to `outputs/clone-evidence.json`.

## 3. Deviations / ADR

Docs describe the implementation and recorded limitations rather than promoting every SPEC
illustration into a verified capability. Production provider/recording, full native visual QA,
real calibration and live reward/learning remain explicit backlog work. No new feature work,
GPU job, paid call, real approval or live publish occurred. Meta's current documentation could
not be retrieved, so version/scopes/quota/limits stay human verification items. Source paper
results are not project measurements. See ADR 0008.

The validation image intentionally retains fresh-checkout Git metadata and dev tools for
`make setup`/hooks; the production CPU image excludes them. Image preparation downloads the
locked dependencies; the gate itself runs offline. No host environment, cache, state or keys
are needed. Final rendered README verification method and any browser limitation are reported
at delivery. The phase's commits and PR use mazenDDr exclusively.

## 4. HUMAN items

- # HUMAN: review/merge the Phase 8 PR.
- # HUMAN: choose and authorize the next backlog item; no post-build work starts automatically.
- # HUMAN: real API credentials/cassettes, brand freeze, benchmark/calibration labels, approved
  crops and GPU/FLF/runtime/QA spikes remain pending.
- # HUMAN: native deployment, Tailscale ACLs/worker token, current Meta preparation and intentional
  publishing/insights require the go-live prerequisites, not merely completion of phase gates.

## 5. Proposed next step

The eight planned offline build phases end here after the gate and review/merge. The proposed
follow-up is production LLM/recording integration, followed by independently measured native
validation. That is a new scoped task; it is not implemented or authorized by this phase report.
