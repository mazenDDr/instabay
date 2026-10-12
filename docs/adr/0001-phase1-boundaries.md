# ADR 0001: Phase 1 boundaries and offline persistence

Phase 1 uses a provider-independent `LLMClient` and `CallStore`, Pydantic request/response
models, file-backed canned fixtures and a small standard-library SQLite cache/ledger.
SQLModel business tables, LangGraph, approved publishing and domain agents wait for Phase 2;
adding them now would cross the phase gate. Empty package directories represent the later
layout, but `sim/` is deliberately absent until its required separate Phase 3 commit.
Fixtures follow §15 while removing its illustrative unverified house-reef/room claims,
because the no-invented-facilities hard rule wins. The supplied root `SPEC.md` moved to
`docs/SPEC.md` to match the existing instructions. Future-phase commands exit honestly
instead of fabricating results. Dependency setup uses network access; lint and test execution
are offline. The user's explicit request authorizes separate internet photo retrieval and
SSH connectivity checks, while real model runs and GPU renders remain human tasks. Git
uses the requested sole-author identity; the phase branch uses a neutral `feat/` prefix.
