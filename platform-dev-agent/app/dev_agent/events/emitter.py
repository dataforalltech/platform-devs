"""EventEmitter — constrói o envelope (ADR-012) e encadeia a causalidade.

Um emitter é ligado a UMA execução (`correlation_id = run_id`); cada evento que
emite recebe `causation_id = id do evento anterior` (cadeia causal D12.4). O `data`
carrega só refs/metadados (ids, status, contagens, latência) — nunca payload cru
(D12.9). Sem sink (ou NullEventSink), emitir é no-op barato.
"""

from __future__ import annotations

from app.dev_agent.events.model import Event, EventType
from app.dev_agent.events.sink import EventSink, NullEventSink


class EventEmitter:
    def __init__(self, sink: EventSink | None, *, correlation_id: str,
                 tenant_id: str | None = None, session_id: str | None = None,
                 source: str = "/platform-dev-agent/runtime") -> None:
        self._sink = sink or NullEventSink()
        self._corr = correlation_id
        self._tenant = tenant_id
        self._session = session_id
        self._source = source
        self._last_id: str | None = None      # raiz da cadeia causal

    def _emit(self, type_: EventType, subject: str, data: dict) -> Event:
        ev = Event(type=type_, subject=subject, data=data, tenant_id=self._tenant,
                   session_id=self._session, correlation_id=self._corr,
                   causation_id=self._last_id, source=self._source)
        self._sink.emit(ev)
        self._last_id = ev.id                  # encadeia o próximo
        return ev

    # --- plan / approval ----------------------------------------------------
    def plan_created(self, *, plan_id: str, run_id: str | None, goal: str,
                     runbook_id: str, task_count: int) -> Event:
        return self._emit(EventType.PLAN_CREATED, f"plan/{plan_id}",
                          {"plan_id": plan_id, "run_id": run_id, "goal": goal,
                           "runbook_id": runbook_id, "task_count": task_count})

    def plan_approved(self, *, plan_id: str, run_id: str, level: str, auto: bool) -> Event:
        return self._emit(EventType.PLAN_APPROVED, f"plan/{plan_id}",
                          {"plan_id": plan_id, "run_id": run_id, "level": level, "auto": auto})

    def approval_denied(self, *, plan_id: str, run_id: str, reason: str) -> Event:
        return self._emit(EventType.APPROVAL_DENIED, f"plan/{plan_id}",
                          {"plan_id": plan_id, "run_id": run_id, "level": "N1", "reason": reason})

    # --- execution ----------------------------------------------------------
    def execution_started(self, *, run_id: str, plan_id: str, resume: bool = False) -> Event:
        return self._emit(EventType.EXECUTION_STARTED, f"run/{run_id}",
                          {"run_id": run_id, "plan_id": plan_id, "resume": resume})

    def task_started(self, *, run_id: str, task_id: str, operation_id: str,
                     tool: str, attempt: int = 1) -> Event:
        return self._emit(EventType.TASK_STARTED, f"task/{task_id}",
                          {"run_id": run_id, "task_id": task_id, "operation_id": operation_id,
                           "tool_ref": tool, "attempt": attempt})

    def task_finished(self, *, run_id: str, task_id: str, status: str,
                      duration_ms: int = 0, error: str | None = None) -> Event:
        return self._emit(EventType.TASK_FINISHED, f"task/{task_id}",
                          {"run_id": run_id, "task_id": task_id, "status": status,
                           "duration_ms": duration_ms, "error": error})

    def execution_completed(self, *, run_id: str, plan_id: str, status: str,
                            tasks_ok: int, tasks_failed: int) -> Event:
        return self._emit(EventType.EXECUTION_COMPLETED, f"run/{run_id}",
                          {"run_id": run_id, "plan_id": plan_id, "status": status,
                           "tasks_ok": tasks_ok, "tasks_failed": tasks_failed})

    def runbook_completed(self, *, run_id: str, runbook_id: str, status: str,
                          steps_total: int, steps_ok: int) -> Event:
        return self._emit(EventType.RUNBOOK_COMPLETED, f"run/{run_id}",
                          {"run_id": run_id, "runbook_id": runbook_id, "status": status,
                           "steps_total": steps_total, "steps_ok": steps_ok})

    # --- capability / policy (borda de execução) ----------------------------
    def capability_invoked(self, *, run_id: str, operation_id: str, tool: str,
                           provider_id: str, authz: str, risk_level: str,
                           blast_radius: str, outcome: str, latency_ms: int) -> Event:
        return self._emit(EventType.CAPABILITY_INVOKED, f"capability/{operation_id}",
                          {"run_id": run_id, "operation_id": operation_id, "tool_id": tool,
                           "provider_id": provider_id, "authz": authz, "risk_level": risk_level,
                           "blast_radius": blast_radius, "outcome": outcome,
                           "latency_ms": latency_ms})

    def policy_denied(self, *, run_id: str, operation_id: str | None, actor: str,
                      reason: str) -> Event:
        return self._emit(EventType.POLICY_DENIED, f"capability/{operation_id or 'unknown'}",
                          {"run_id": run_id, "operation_id": operation_id, "actor": actor,
                           "reason": reason})

    # --- asset lifecycle (ADR-014 emite; envelope/tópico ADR-012) -----------
    def asset_published(self, *, asset_ref: str, kind: str, version: str,
                        owner: str) -> Event:
        return self._emit(EventType.ASSET_PUBLISHED, f"asset/{asset_ref}",
                          {"asset_ref": asset_ref, "kind": kind, "version": version,
                           "owner": owner})

    def asset_promoted(self, *, asset_ref: str, kind: str, version: str,
                       from_: str, to: str, approver: str) -> Event:
        return self._emit(EventType.ASSET_PROMOTED, f"asset/{asset_ref}",
                          {"asset_ref": asset_ref, "kind": kind, "version": version,
                           "from": from_, "to": to, "approver": approver})
