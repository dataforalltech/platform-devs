# Catalog gaps — Runbooks wave-1 (Fase 6)

Operation-first (ADR-009/ADR-014/ADR-016): a runbook task binds to a catalog
**Operation**, never to a Tool directly. While authoring the wave-1 runbooks
(`hotfix`, `architecture_review`, `incident`) we hit capabilities that **no
existing Operation** covers.

Per the governing rules we **do not invent Operations** and **do not bind a Tool
directly** to fill a gap. Instead, the affected steps are **omitted** from the
shipped runbooks, and the missing capabilities are recorded here as **candidate
Operations** (proposals for a future catalog change — NOT bindings, NOT tasks).

Until these candidate Operations land in `platform-catalog/catalog/operations/`
(and gain at least one Tool binding under `catalog/tools/` — or federated under
`catalog/external/`), the runbooks stay smaller rather than reach past the
catalog.

---

## Candidate Operations

### 1. Structured ADR retrieval — needed by `architecture_review`

Today only `governance.create_adr` exists (write). There is **no read Operation**
to list or fetch ADRs, so `architecture_review` cannot pull the governing ADRs
into the review. The `search_knowledge` step (`governance.search_governance_knowledge`)
is the closest available read, but it is free-text search, not structured ADR
retrieval.

| proposed operation_id | domain     | authz | rationale | needed by |
|-----------------------|------------|-------|-----------|-----------|
| `governance.list_adrs` | governance | read | Enumerate ADRs (id, title, status) so a review can select the relevant decisions. | `architecture_review` |
| `governance.get_adr`   | governance | read | Fetch one ADR's full content/status by id for structured validation against the design. | `architecture_review` |

**Omission:** `architecture_review` performs its checks against service metadata,
the ecosystem graph, layer/scope policy, governance knowledge search, and the
compliance audit — but it does **not** include an ADR-retrieval step, because
binding it would require inventing an Operation.

---

### 2. Incident lifecycle — needed by `incident`

There is **no incident domain** in this catalog. An incident-response runbook
should be able to declare an incident, update its status as it progresses, and
resolve it — none of which map to an existing Operation.

| proposed operation_id     | domain   | authz | rationale | needed by |
|---------------------------|----------|-------|-----------|-----------|
| `incident.declare`        | incident | write | Open/declare an incident record (severity, affected service, summary) to anchor the lifecycle. | `incident` |
| `incident.update_status`  | incident | write | Advance incident state (investigating → mitigating → monitoring) as the response proceeds. | `incident` |
| `incident.resolve`        | incident | write | Close the incident once recovery is verified. | `incident` |

**Omission:** `incident` covers detect → diagnose → mitigate → verify using the
existing `infra.*` and `delivery.*` Operations (health, logs, deploy/promotion
history, rollback/block/reload, recovery check) plus artifact capture and
post-mortem doc — but the **incident-record lifecycle** (declare/update/resolve)
is omitted.

---

### 3. On-call paging & status communication — needed by `incident` (federation)

Incident response needs to page on-call and post status communications. There is
**no notification/communication Operation in this catalog**. Per ADR-009 §1.1,
communication capabilities live in a **separate gateway (`platform-communication`)
that is not yet federated** into this catalog — this is a **federation gap**, not
a capability to be invented locally.

| proposed operation_id (in the communication gateway) | domain        | authz | rationale | needed by |
|------------------------------------------------------|---------------|-------|-----------|-----------|
| e.g. `communication.page_on_call`                    | communication | write | Page the on-call engineer when an incident is detected. | `incident` |
| e.g. `communication.post_status`                     | communication | write | Post incident status updates to a status channel. | `incident` |

**Resolution path:** federate `platform-communication` into the catalog (ADR-009
§1.1 federation — the same mechanism used for the admin/auth external Operations
under `catalog/external/`). This is **federation, not a local invention**.

**Omission:** `incident` includes no paging or status-communication step until
the `platform-communication` gateway is federated.

---

## Summary

Until the candidate Operations above are added to the catalog (and bound to a
Tool, or federated), the wave-1 runbooks **omit** the corresponding steps rather
than bind a Tool directly. This keeps every shipped runbook task Operation-first
and 100% resolvable against the current catalog.
