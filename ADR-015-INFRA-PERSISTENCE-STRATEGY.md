# ADR-015: Infra Persistence Strategy — Selective SQLite Retention

**Status**: ACCEPTED
**Date**: 2026-07-06
**Deciders**: caiog
**Affects**: `infra-mcp-server`, `session-mcp-server`
**Amends**: [ADR-001](ADR-001-PYTHON-POSTGRESQL-MIGRATION.md) (scoped exception)

---

## Context

[ADR-001](ADR-001-PYTHON-POSTGRESQL-MIGRATION.md) established the platform principle
*"PostgreSQL is the source of truth; no SQLite fallback."* A later migration
(commit `bbdda58`, *"Migrate 6 MCPs from SQLite to PostgreSQL"*) moved a second wave of
servers (audit, deploy, docs, infra, test, dev-twin) from embedded SQLite to a psycopg2
PostgreSQL store.

That migration landed **unevenly**:

- **audit, config, deploy, docs, test, dev-twin** — the PG store is a working CRUD layer.
  Tests are hermetic by **mocking the psycopg2 pool**. These stay on PostgreSQL (fix-forward).
- **infra-mcp (`AllocatorStore`) and session-mcp** — the migration left the store as
  non-functional `NotImplementedError` skeletons whose `__init__` demanded a live PG pool,
  while the **entire test suite is SQLite `:memory:`**. Nothing worked and nothing was tested.

`infra-mcp` is the hard case: `AllocatorStore` is not CRUD. It performs concurrent VM
allocation with leases, queues, preemption and garbage-collection, and today relies on a
`threading.RLock` for in-process concurrency. A **correct** PostgreSQL port is not a
mechanical translation — it requires row-level locking (`SELECT … FOR UPDATE`), explicit
transaction isolation, and **integration tests against a real/containerized PostgreSQL** to
prove the concurrency semantics. A unit test with a mocked pool would *look* complete while
proving nothing about correctness for the very server where correctness is hardest.

## Decision

1. **SQLite (embedded) is the official backend for `infra-mcp` and `session-mcp`** until a
   complete, concurrency-safe PostgreSQL implementation exists. The working SQLite store was
   restored (infra: from `d0d8791`) and the misleading, inert `pg_*` configuration was removed
   from `infra-mcp/src/config/settings.py`.
2. **All other `bbdda58` servers remain on PostgreSQL** (fix-forward, psycopg2 pool mocked in
   tests). This ADR does **not** revert them.
3. This is a **deliberate, temporary, single-backend choice per server** — *not* a dual-DB
   fallback. ADR-001's principle stands for the fleet; infra/session are explicitly-scoped
   exceptions with the exit criteria below.

### Migration criteria (when infra/session move to PostgreSQL)

A server leaves this exception only when **all** hold:

1. The PG store implements every method with **row-level locking** for concurrent allocation
   (no reliance on a process-local lock).
2. **Integration tests run against a real/containerized PostgreSQL** — not only a mocked pool.
3. Lease / queue / preemption / GC semantics are verified **under concurrency**.
4. The deployment provisions a PostgreSQL instance reachable by these servers.

Tracked as follow-up **`task_79edfb46`**.

## Consequences

### Positive
- CI is honestly green: working, tested code instead of a fake-done PG port.
- No unverified concurrency SQL shipped for the highest-risk server.
- Clear, auditable exit criteria rather than an implicit "TODO".

### Risks & trade-offs
| Risk | Mitigation |
|------|-----------|
| Two backends in the fleet (temporary inconsistency) | Scoped to 2 servers + documented exit criteria |
| SQLite `:memory:` is not durable across restarts | Set `INFRA_DB_PATH=/data/allocator.db` to persist |
| SQLite is not shareable across instances | infra/session run **single-instance** until PG lands |

## Alternatives Considered

1. **Implement PostgreSQL now, tests with a mocked pool** — REJECTED: passes CI without
   proving concurrency correctness; highest-risk server, worst place to fake "done".
2. **Leave the servers broken / CI red** — REJECTED: blocks the merge and the whole fleet gate.
3. **SQLite officially + explicit migration criteria** — **SELECTED**.

## Related Decisions

- [ADR-001](ADR-001-PYTHON-POSTGRESQL-MIGRATION.md) — the fleet PostgreSQL principle this ADR
  scopes an exception to.
- [ADR-016](ADR-016-CI-VALIDATION-STRATEGY.md) — the hermetic-test principle (mocked stores)
  that makes fix-forward viable for the other migrated servers.

---

**Approval**: ✅ ACCEPTED (2026-07-06)
