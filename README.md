# Insta Bay

An approval-first Instagram marketing system for a fictional Red Sea resort in Hurghada.
The intended weekly loop is brand → plan → native EN/AR content → checks → human approval
→ publishing → metrics → learning. **LLMs write, statistics decide, a human approves.**

## Current status

Phase 1 implements the Python 3.12 scaffold, `FakeLLM`, prompt hashing, schema validation,
one validation retry, usage budgets, a persistent SQLite LLM cache and call ledger,
offline tests, strict lint/type checks, local pre-commit hooks, CI and a Docker smoke image.
Agents, human approval, publishing, simulation, optimization, benchmarks and video rendering
are scheduled for later phases in [the specification](docs/SPEC.md).
`make demo`, `make bench`, `make render`, and `instabay cycle` currently exit with a
clear phase-specific message; they do not claim to run the future system.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
make setup test lint
make smoke
```

Setup downloads the locked runtime and dependencies. Tests and lint use `uv --offline
--no-sync`; pytest blocks network sockets. No API keys, GPU or paid services are required.
Local hooks use the project's `.venv`, so they do not clone additional hook repositories.
If uv was bootstrapped locally in `.tools/bin/uv`, the Makefile detects it automatically.

```sh
docker build -t instabay:phase1 .
docker run --rm instabay:phase1
```

The smoke command composes canned EN and AR examples. It records each actual provider
attempt, including schema failures, in `outputs/instabay.sqlite3`. A repeat invocation
loads the stored output without another provider call and logs a zero-cost cache hit.
Fixture token counts are illustrative; fake calls cost $0 and are not real model benchmarks.

## Reproducibility and safety

Prompts are Markdown files; the AR copywriter prompt is written in Arabic. Cache keys include
the exact prompt hash, inputs, slot, model, output schema, temperature and token limit.
Invalid output gets one retry with sanitized validation feedback, then raises an error.
Only valid output within the run budget enters the cache. Corrupt cache entries are evicted.
The ledger records UTC times, tokens, cost, latency and safe error categories, without
prompts, input text, raw failed output or provider error messages.
Actual token/cost overrun is detected after a provider response, recorded, and halts the run;
a provider whose API does not expose preflight usage cannot guarantee an exact spend ceiling.

The default configuration is `dry_run`. Secrets belong in git-ignored `.env` or CI secrets;
`.env.example` contains empty credential fields. No real-provider adapter exists yet.
Publishing will require a stored APPROVED/EDITED decision, plus explicit live confirmation.

## Reference photography

The user-requested photo pack is tracked separately under `assets/photos/`. It depicts
**The Grand Resort Hurghada**, not an actual property named Insta Bay. Each asset has its
source, author, license, dimensions and SHA-256 in the manifest. Historical reference
photos do not establish current facilities or offers. See its attribution README before
using the photos or derivative footage. Video recipes and human approval arrive in Phase 7.

## Human follow-up

- # HUMAN: run Phase 0 GPU/model spikes and record `docs/adr/0000-spikes.md`.
- # HUMAN: create provider keys and Meta tokens; record real LLM cassettes.
- # HUMAN: edit and freeze the brand constitution in Phase 2.
- # HUMAN: supply benchmark ratings in Phase 4.

The simulator must be committed separately **before** optimizer code is introduced.
