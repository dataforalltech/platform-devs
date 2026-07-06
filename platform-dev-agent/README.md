# platform-dev-agent (PoC walking skeleton)

> **This is a PoC subdirectory** of `platform-devs`. It will be extracted into
> its own repo later. Do **not** run `git init` here — it is tracked by the
> parent repo for now.

## Scope

Steps 1–4 of the senior critique's *walking skeleton*: prove
**runbook DAG → Plan → (executor) → gateway** wiring for a single linear,
read-only pipeline, before any persona/executor/approval/leader machinery.

Implemented here (and **only** this):

| Module | What it does |
|---|---|
| `app/core/config.py` | `Settings` (pydantic-settings): gateway URL/timeouts, `tool_max_retries`, `resume_writes_safe=False`, per-run ceilings (`max_tokens`, `max_wall_clock_s`, `max_tool_calls`, `max_plan_items`). |
| `app/dev_agent/models/plan.py` | `Plan`, `PlanItem` (incl. `required`), `ItemResult`, StrEnums (`Capability`, `RiskLevel`, `ItemStatus` incl. `NEEDS_RECONFIRM`, `PlanStatus`). Validator: `tool` must be `<namespace>.<operationId>`. |
| `app/dev_agent/capability.py` | `CapabilityResolver` — the **single authority**. Capability from verb (`create_/update_/delete_/generate_/deploy_` → write); risk derived structurally from `MUTATION + owner∈{deploy,infra,pipeline}` (not a nominal allow-list). |
| `app/dev_agent/gateway/client.py` | `GatewayToolClient` — Streamable HTTP + OAuth via async `token_provider`; JSON-RPC `tools/call`; always sends `Idempotency-Key`; correlation headers; tenacity retry **for reads only**. |
| `app/dev_agent/runbook/catalog.py` + `dag.py` | `RunbookTaskSpec`/`RunbookSpec` (versioned); one linear read-only runbook `check_health → run_tests → generate_report`; Kahn `topological_order` with cycle + orphan detection → `RunbookDAGError`. |
| `app/dev_agent/plan/builder.py` | `PlanBuilder.build_from_runbook` — topo-sort, resolve capability+risk, validate `input_data` against `input_schema` (fail early), propagate `required`, stamp `runbook_version`. |

## NOT in scope (deliberately)

Personas, `PlanExecutor`, `ApprovalGate`, leader/dispatch, `PlanRepository`.
Those are later E2Es.

## Idempotency / resume note

The platform-mcp gateway does **not** deduplicate writes by `Idempotency-Key`
(it only retries reads). So `resume_writes_safe` defaults to `False` and
resuming a write is the executor's responsibility (out of this skeleton). The
client therefore retries **reads only**; writes are attempted exactly once.

## Running

```bash
python -m pip install -e ".[dev]"
python -m pytest -q            # unit tests
```

The gateway integration test (`tests/test_gateway_integration.py`) is skipped
unless `DEV_GATEWAY_URL` is set. To run it against a live gateway:

```bash
DEV_GATEWAY_URL=https://platform-mcp/.../mcp \
DEV_GATEWAY_TOKEN=<bearer> \
DEV_GATEWAY_READ_TOOL=services-mcp.list_services \
python -m pytest tests/test_gateway_integration.py -q
```
