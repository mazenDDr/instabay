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

| Check | Result |
|---|---|
| Fresh clone | Clean committed checkout at `d0edca7`; no host environment/cache/state used. |
| Docker setup/demo/test/lint | `make setup demo test lint` succeeds as UID 10001 with networking disabled; **252 tests**, Ruff, **126 formatted files**, strict mypy in **83 files**. |
| Persistent default demo | **7 drafts**, `approval_pending`, **0 approvals/publications/metrics/posteriors/render jobs**, no outbox. Database and checkpoint existence/status checked explicitly. |
| Repository hooks | Ruff, format, strict typing and secret scanning all pass inside the unprivileged container. |
| Runtime image | Separate `instabay:phase8` image built; network-disabled default demo reaches the human approval stop. |
| Documentation | Eight key Markdown files and 41 local links checked; balanced code fences; generated benchmark block preserved byte-for-byte. |
| Protected inputs | SPEC, application/config/model code, simulator, photos and benchmark JSON unchanged. |

Machine-readable clone evidence is generated at `outputs/clone-evidence.json` inside the image;
the local transcript/evidence is retained privately. One expected test warning records an explicit
blocked TCP attempt; ASGI event-loop Unix socketpairs are the only test-local allowance. No keys
or GPU are used. Fresh-clone CI runs the same gate; final exact-head status is reported at delivery.
The first acceptance attempt passed the demo/tests but failed the final hook cache at `/.cache`;
a project-local cache fixed it, and the full sequence passed on the fresh corrected checkout.

## 3. Deviations / ADR

Docs describe the implementation and recorded limitations rather than promoting every SPEC
illustration into a verified capability. Production provider/recording, full native visual QA,
real calibration and live reward/learning remain explicit backlog work. No new feature work,
GPU job, paid call, real approval or live publish occurred. Meta's current documentation could
not be retrieved, so version/scopes/quota/limits stay human verification items. Source paper
results are not project measurements. See ADR 0008.

The validation image intentionally retains fresh-checkout Git metadata and dev tools for
`make setup`/hooks; the production CPU image excludes them. Image preparation downloads the
locked dependencies; the gate itself runs offline. Checkout credentials, inherited hooks and reflogs are excluded; CI checkout does not
persist credentials. No host environment, cache, state or keys are needed. Final rendered README verification method and any browser limitation are reported
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
