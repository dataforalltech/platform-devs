# ADR-016: CI Validation Strategy for the MCP Server Fleet

**Status**: ACCEPTED
**Date**: 2026-07-06
**Deciders**: caiog
**Affects**: CI of all `*-mcp-server` (`.github/workflows/`: `test-all-mcps.yml`, `ci.yml`,
`mcp-dod.yml`, `ai-governance-mcp-ci.yml`, `devteam-python-ci.yml`)

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

The following validation principles are the standard for every server in a CI matrix.

1. **Hermetic tests.** Tests make **no real I/O** — no database, network, subprocess,
   filesystem side-effects, or real sleeps. All external dependencies are mocked
   (`monkeypatch` / `unittest.mock`; PG stores via a mocked psycopg2 pool). A test that hangs
   or reaches a real host (e.g. a Postgres at `claude-dev`) is a defect, not a passing test.

2. **Fresh, CI-faithful verification.** "Green locally" is only trusted when verified in a
   **brand-new clean virtualenv** via `pip install -e ".[dev]"`. A reused/leaky venv hides
   dependencies that are installed but **not declared** — exactly how the `pytest-cov` gap
   below stayed invisible.

3. **Mandatory test plugins in `[dev]`.** Because the gate runs `pytest --cov`, every server's
   `[project.optional-dependencies].dev` must declare: `pytest`, `pytest-asyncio` (async tests),
   `pytest-mock`, and **`pytest-cov`**. A missing `pytest-cov` makes a clean CI install fail with
   *"unrecognized arguments: --cov"*.

4. **Coverage ≥ 80%**, measured `--cov=src`. **No gate-weakening**: no lowered threshold, no
   blanket `# noqa`, no `--no-cov`, no `skip`/`xfail` used to hide a real failure. A `skip` is
   acceptable only for a test that genuinely cannot run in CI, with a documented `reason=`.

5. **`fail-fast: false` on every test matrix.** One server's failure must never cancel or mask
   its siblings (it did on PR #18 — one failure cancelled nine passing legs and obscured the
   diagnosis). `test-all-mcps.yml` already set this; `ci.yml` now does too.

6. **Matrix membership defines the gate.** Only servers listed in a CI matrix are gated. The
   eight "template" servers (architecture, backend, devops, frontend, product-owner,
   product-manager, qa-engineer, security) are intentionally **not** in a Python test matrix;
   adding tests for them does not change CI status. Adding a server to the fleet means adding
   it to the matrix **and** giving it the `[dev]` plugins + a hermetic suite.

7. **Lint is authoritative, verified with the pinned tool.** `ruff check` and
   `ruff format --check` must be clean, run with the **ruff pinned in `.[dev]`** — never
   approximated by an ad-hoc `grep` (ruff's `-->` diagnostic format is easy to miss and yields
   false negatives).

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
