# ADR-016: CI Validation Strategy for the MCP Server Fleet

**Status**: ACCEPTED
**Date**: 2026-07-06
**Deciders**: caiog
**Affects**: the platform's automated validation gate for every `*-mcp-server`
**Scope note**: the rules below are **CI-system- and tool-agnostic principles**. Each parenthetical
*(today: …)* cites the current implementation (GitHub Actions + pytest / ruff / vitest) and may
change without invalidating the principle. Current workflows: `test-all-mcps.yml`, `ci.yml`,
`mcp-dod.yml`, `ai-governance-mcp-ci.yml`, `devteam-python-ci.yml`.

---

## Context

The fleet's CI drifted into a broadly-red state (PR #18 reported **44 of 50 checks failing**).
Stabilization revealed the failures were not one problem but several classes: test
dependencies missing from `[dev]`, migration debt (broken imports, dead files, non-functional
stores), obsolete workflows referencing deleted files, and a matrix `fail-fast` that cancelled
healthy jobs and masked the real cause. Remediation restored the branch to
**49 checks passed · 1 skipped (expected, `integration-test` runs only on push) · 0 failures**.

> **Reporting note.** State CI status as explicit counts —
> *"N passed / M skipped (expected) / K failures"* — not as *"100% green"* or *"totally green"*.
> Skips are legitimate and expected; precise counts match the GitHub checks panel and avoid
> misinterpretation when someone cross-references it.

These principles are formalized here so they are not buried in commit history.

## Decision

The following are **durable engineering principles** for the platform's validation gate. Each
states the principle first; the parenthetical *(today: …)* is the current implementation and may
change (tooling, CI provider) **without invalidating the principle**.

1. **Tests are hermetic.** A test exercises only the code under test — **no real I/O**: no
   database, network, subprocess, filesystem side-effects, or wall-clock sleeps. External
   dependencies are substituted with test doubles. A test that hangs or reaches a real host is a
   defect, not a pass. *(today: `monkeypatch`/`unittest.mock`; DB stores via a mocked psycopg2
   pool — a suite once hung reaching a real Postgres at `claude-dev`.)*

2. **The gate is reproducible from a clean, isolated environment**, using **only declared
   dependencies** — never ambient or pre-installed tooling. *(today: a brand-new virtualenv +
   `pip install -e ".[dev]"`; for TypeScript servers, a clean `npm ci`.)*

3. **The dependency manifest is self-sufficient for the whole gate.** Everything the gate runs
   must be a declared dependency; a clean install alone must be able to run lint, type-check,
   tests and coverage. *(today, Python: `pytest`, `pytest-asyncio`, `pytest-mock`, `pytest-cov`
   in `[dev]` — a missing `pytest-cov` broke `--cov` on a clean install and stayed invisible in
   a reused/leaky venv; TS: the equivalent `devDependencies`.)*

4. **A minimum coverage bar is enforced honestly.** Source coverage must meet the platform bar,
   and the gate is **never weakened to pass** — no lowered threshold, no blanket suppression, no
   disabling coverage, no `skip`/`xfail` to hide a real failure (a skip is legitimate only for a
   test that genuinely cannot run in the environment, with a documented reason). *(today: ≥ 80%
   over `--cov=src`.)*

5. **A component's failure never masks another's.** Independent units of the gate report
   independently; one failure must not cancel or hide the others. *(today: `fail-fast: false` on
   every test matrix — a single failure once cancelled nine passing legs on PR #18 and obscured
   the diagnosis.)*

6. **What is gated is explicit.** Gate coverage is intentional and visible: a component is either
   in the gate (with a hermetic suite + self-sufficient manifest) or explicitly out; adding a
   component to the fleet means adding it to the gate. *(today: the servers listed in the CI
   matrices; the eight "template" servers — architecture, backend, devops, frontend,
   product-owner, product-manager, qa-engineer, security — are intentionally out of the Python
   test matrix, so adding tests for them does not change gate status.)*

7. **Lint/format is authoritative and machine-verified with the project-pinned tool** — the
   tool's own output is the source of truth, never approximated by ad-hoc parsing. *(today:
   `ruff check` + `ruff format --check` from the pinned `ruff`; an ad-hoc `grep` missed ruff's
   `-->` diagnostic format and produced false negatives.)*

8. **Status is reported by objective counts**, never "100% / totally green" (see the Reporting
   note above): *"N passed / M skipped (expected) / K failures"*, matching the checks panel.

## Consequences

### Positive
- CI is reproducible, non-flaky, and honestly reported.
- A concrete Definition-of-Done for new servers; onboarding is mechanical.
- Failures are diagnosable (no fail-fast masking; fresh-venv reproduction).

### Trade-offs
- Per-server virtualenvs and explicit plugin declarations add minor overhead.
- Hermetic mocking is more test code up front — paid back in speed and determinism.

## Related Decisions

- [ADR-015](ADR-015-INFRA-PERSISTENCE-STRATEGY.md) — the hermetic-test principle (mocked
  stores) is what lets the migrated servers stay on PostgreSQL without a live DB in CI.
- **MCP Service Standard §11 (Definition of Done)** — enforced by `mcp-dod.yml`; this ADR is
  the CI-mechanics companion to that standard.

---

**Approval**: ✅ ACCEPTED (2026-07-06)
