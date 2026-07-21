"""Store do session-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do SQLite/psycopg2-fachada para o **Repository** de alto nível + Query IR,
ligado ao pool **do tenant** (resolvido credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12). Roda dual-db: o mesmo código serve MySQL
(banco-por-tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`update_where`/
`upsert`/`delete_where`/`count`). Operações que "não encaixam" no CRUD trivial
resolvem canonicamente:
  * vínculo de serviço por (session_id, service) -> `upsert(conflict_columns=[...])`
    (ON DUPLICATE KEY no MySQL / ON CONFLICT no PG) — reativa a linha soft-deletada;
  * summary de tasks por status / próximo sort_order / contagem de pendências ->
    agregação em Python sobre `find().rows()` (dado minúsculo por-sessão; evita
    GROUP BY/MAX e mantém orm-lint --strict limpo);
  * transições de estado (task/suggestion) -> find + update_where condicional.

Chave de negócio: a fábrica canônica injeta um surrogate ``id`` autoincrement como
PK; o antigo ``sessions.id`` (``sess_<hex>``) vira ``session_uid VARCHAR`` UNIQUE, e
as tabelas-filho referenciam esse valor por ``session_id``. O store mapeia
``session_uid`` -> ``id`` na saída, preservando o contrato das tools.

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`) — os atores de negócio (actor_id,
promoted_by, ...) continuam sendo strings em colunas próprias.
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import UTC, date, datetime
from typing import Any

from platform_database.orm import And, Condition, Operator, Sort, SortDirection

from ..models import (
    ArtifactRow,
    CheckpointRow,
    DecisionRow,
    ServiceDepRow,
    SessionRow,
    SuggestionRow,
    TaskRow,
)
from .schema import (
    ARTIFACTS_TABLE,
    CHECKPOINTS_TABLE,
    DECISIONS_TABLE,
    SESSION_SERVICES_TABLE,
    SESSIONS_TABLE,
    SUGGESTIONS_TABLE,
    TASKS_TABLE,
)

logger = logging.getLogger(__name__)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O ator de negócio real viaja em colunas próprias (actor_id, promoted_by, ...).
_SYSTEM_USER = 0

TASK_STATUSES = ("pending", "in_progress", "completed", "failed", "cancelled")
TASK_OPEN_STATUSES = ("pending", "in_progress")
TASK_TERMINAL_STATUSES = ("completed", "failed", "cancelled")

SUGGESTION_STATUSES = ("pending", "accepted", "rejected", "deferred", "superseded")
SUGGESTION_KINDS = ("improvement", "correction", "addition", "question", "other")
SUGGESTION_PRIORITIES = ("low", "medium", "high", "critical")

ACTOR_TYPES = ("human", "agent", "system")

_ASC = SortDirection.ASC
_DESC = SortDirection.DESC


def _generate_name() -> str:
    """Gera um nome único para a sessão no formato <adjetivo>-<personagem>."""
    adjectives = ["ancient", "blazing", "bold", "calm", "cosmic", "clever", "daring", "divine"]
    names = ["zeus", "odin", "athena", "batman", "marvel", "goku", "loki", "thor"]
    return f"{random.choice(adjectives)}-{random.choice(names)}"  # noqa: S311


def _now() -> str:
    """Retorna ISO timestamp com timezone."""
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    """Gera um session uid no formato sess_<8 hex>."""
    return f"sess_{uuid.uuid4().hex[:8]}"


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Converte datetimes das colunas padrão (create_on/timestamp_refresh) em ISO str,
    para o `json.dumps` do envelope MCP não quebrar."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return out


def _eq(column: str, value: Any) -> Condition:
    return Condition(column=column, op=Operator.EQ, value=value)


class SessionStore:
    """Store tenant-scoped: 7 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._sessions = session.repository(SessionRow, table_name=SESSIONS_TABLE)
        self._checkpoints = session.repository(CheckpointRow, table_name=CHECKPOINTS_TABLE)
        self._artifacts = session.repository(ArtifactRow, table_name=ARTIFACTS_TABLE)
        self._tasks = session.repository(TaskRow, table_name=TASKS_TABLE)
        self._services = session.repository(ServiceDepRow, table_name=SESSION_SERVICES_TABLE)
        self._suggestions = session.repository(SuggestionRow, table_name=SUGGESTIONS_TABLE)
        self._decisions = session.repository(DecisionRow, table_name=DECISIONS_TABLE)

    # ── helpers de leitura (dict cru) ─────────────────────────────────────────

    async def _session_raw(self, session_id: str) -> dict[str, Any] | None:
        res = await self._sessions.find(where={"session_uid": session_id}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _exists_session(self, session_id: str) -> bool:
        return await self._sessions.exists({"session_uid": session_id})

    async def _task_row(self, task_id: int) -> dict[str, Any] | None:
        res = await self._tasks.find(where={"id": task_id}, limit=1)
        rows = res.rows()
        return _jsonable(rows[0]) if rows else None

    async def _service_row(self, session_id: str, service: str) -> dict[str, Any] | None:
        res = await self._services.find(
            where=And(operands=[_eq("session_id", session_id), _eq("service", service)]), limit=1
        )
        rows = res.rows()
        return rows[0] if rows else None

    async def _suggestion_row(self, suggestion_id: int) -> dict[str, Any] | None:
        res = await self._suggestions.find(where={"id": suggestion_id}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _decision_row(self, decision_id: int) -> dict[str, Any] | None:
        res = await self._decisions.find(where={"id": decision_id}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    async def _tasks_summary(self, session_id: str) -> dict[str, int]:
        rows = (await self._tasks.find(where={"session_id": session_id})).rows()
        summary: dict[str, int] = {s: 0 for s in TASK_STATUSES}
        summary["total"] = 0
        for r in rows:
            status = r.get("status")
            if status in summary:
                summary[status] += 1
            summary["total"] += 1
        return summary

    async def _list_service_deps(self, session_id: str) -> list[dict[str, Any]]:
        res = await self._services.find(
            where={"session_id": session_id}, order_by=[Sort(column="id", direction=_ASC)]
        )
        return [_jsonable(r) for r in res.rows()]

    async def _next_sort_order(self, session_id: str) -> int:
        rows = (await self._tasks.find(where={"session_id": session_id})).rows()
        if not rows:
            return 0
        return max((r.get("sort_order") or 0) for r in rows) + 1

    async def _row_to_session(self, row: dict[str, Any]) -> dict[str, Any]:
        d = _jsonable(row)
        business = d.pop("session_uid", None)
        d["id"] = business
        cps = await self._checkpoints.find(
            where={"session_id": business},
            order_by=[Sort(column="id", direction=_DESC)],
            limit=1,
        )
        cp_rows = cps.rows()
        d["last_checkpoint"] = _jsonable(cp_rows[0]) if cp_rows else None
        d["artifacts_count"] = await self._artifacts.count(where={"session_id": business})
        d["tasks_summary"] = await self._tasks_summary(business)
        d["service_dependencies"] = await self._list_service_deps(business)
        return d

    # ────────────────────────────────────────────────────────────────────────── #
    # SESSION OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    async def create_session(
        self,
        title: str,
        objective: str,
        repo: str | None = None,
        branch: str | None = None,
        base_branch: str | None = None,
        *,
        project_id: str | None = None,
        agent_client: str | None = None,
        environment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cria uma sessão. `repo` é opcional (sessão pode ser project-scoped — ADR-017 D17.3)."""
        session_uid = _new_id()
        name = _generate_name()
        now = _now()
        await self._sessions.insert(
            {
                "session_uid": session_uid,
                "name": name,
                "title": title,
                "objective": objective,
                "repo": repo,
                "branch": branch,
                "base_branch": base_branch,
                "project_id": project_id,
                "agent_client": agent_client,
                "environment_json": (
                    json.dumps(environment, ensure_ascii=False) if environment is not None else None
                ),
                "status": "active",
                "started_at": now,
                "last_updated_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        row = await self._session_raw(session_uid)
        return await self._row_to_session(row) if row else {}

    async def set_session_branch(self, session_id: str, branch: str, base_branch: str | None = None) -> None:
        """Registra a branch da sessão (e sua base)."""
        await self._sessions.update_where(
            {"session_uid": session_id},
            {"branch": branch, "base_branch": base_branch, "last_updated_at": _now()},
            user_id=_SYSTEM_USER,
        )

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retorna a sessão completa (com último checkpoint, contagens e dependências)."""
        row = await self._session_raw(session_id)
        return await self._row_to_session(row) if row else None

    async def list_sessions(
        self,
        status: str | None = None,
        repo: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Lista sessões com filtros opcionais."""
        conds: list[Any] = []
        if status:
            conds.append(_eq("status", status))
        if repo:
            conds.append(Condition(column="repo", op=Operator.CONTAINS, value=repo))
        where: Any = None
        if len(conds) == 1:
            where = conds[0]
        elif conds:
            where = And(operands=conds)
        res = await self._sessions.find(
            where=where,
            order_by=[Sort(column="last_updated_at", direction=_DESC)],
            limit=limit,
        )
        return [await self._row_to_session(r) for r in res.rows()]

    async def update_session(
        self,
        session_id: str,
        status: str | None = None,
        progress: str | None = None,
    ) -> dict[str, Any] | None:
        """Atualiza status e/ou progresso. Retorna a sessão ou None se não existe."""
        if not await self._exists_session(session_id):
            return None
        updates: dict[str, Any] = {"last_updated_at": _now()}
        if status:
            updates["status"] = status
        if progress is not None:
            updates["progress"] = progress
        await self._sessions.update_where({"session_uid": session_id}, updates, user_id=_SYSTEM_USER)
        row = await self._session_raw(session_id)
        return await self._row_to_session(row) if row else None

    async def end_session(
        self,
        session_id: str,
        summary: str = "",
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Encerra a sessão.

        Retorna:
          - dict (sessão) em caso de sucesso;
          - list[dict] com tasks abertas se houver pendências (sessão NÃO encerrada);
          - None se a sessão não existe.
        """
        if not await self._exists_session(session_id):
            return None
        open_rows = (
            await self._tasks.find(
                where=And(
                    operands=[
                        _eq("session_id", session_id),
                        Condition(column="status", op=Operator.IN, value=list(TASK_OPEN_STATUSES)),
                    ]
                ),
                order_by=[
                    Sort(column="sort_order", direction=_ASC),
                    Sort(column="id", direction=_ASC),
                ],
            )
        ).rows()
        if open_rows:
            return [_jsonable(r) for r in open_rows]
        now = _now()
        await self._sessions.update_where(
            {"session_uid": session_id},
            {"status": "completed", "ended_at": now, "last_updated_at": now},
            user_id=_SYSTEM_USER,
        )
        if summary:
            await self._checkpoints.insert(
                {"session_id": session_id, "summary": f"[FINAL] {summary}", "created_at": now},
                user_id=_SYSTEM_USER,
            )
        row = await self._session_raw(session_id)
        return await self._row_to_session(row) if row else None

    # ────────────────────────────────────────────────────────────────────────── #
    # CHECKPOINT OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    async def save_checkpoint(
        self,
        session_id: str,
        summary: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Salva um checkpoint de progresso."""
        now = _now()
        context_json = json.dumps(context, ensure_ascii=False) if context else None
        res = await self._checkpoints.insert(
            {
                "session_id": session_id,
                "summary": summary,
                "context_json": context_json,
                "created_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        await self._sessions.update_where(
            {"session_uid": session_id}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        return {
            "checkpoint_id": int(res.returned_id) if res.returned_id is not None else None,
            "session_id": session_id,
            "summary": summary,
            "saved_at": now,
        }

    async def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """Lista checkpoints de uma sessão (mais recente primeiro)."""
        res = await self._checkpoints.find(
            where={"session_id": session_id}, order_by=[Sort(column="id", direction=_DESC)]
        )
        return [_jsonable(r) for r in res.rows()]

    # ────────────────────────────────────────────────────────────────────────── #
    # ARTIFACT OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    async def add_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content: str,
    ) -> dict[str, Any]:
        """Registra um artefato (arquivo alterado, decisão, etc)."""
        now = _now()
        res = await self._artifacts.insert(
            {"session_id": session_id, "type": artifact_type, "content": content, "created_at": now},
            user_id=_SYSTEM_USER,
        )
        await self._sessions.update_where(
            {"session_uid": session_id}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        return {
            "artifact_id": int(res.returned_id) if res.returned_id is not None else None,
            "session_id": session_id,
            "type": artifact_type,
            "content": content,
            "created_at": now,
        }

    async def list_artifacts(
        self,
        session_id: str,
        artifact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista artefatos de uma sessão."""
        conds: list[Any] = [_eq("session_id", session_id)]
        if artifact_type:
            conds.append(_eq("type", artifact_type))
        where = conds[0] if len(conds) == 1 else And(operands=conds)
        res = await self._artifacts.find(where=where, order_by=[Sort(column="id", direction=_DESC)])
        return [_jsonable(r) for r in res.rows()]

    # ────────────────────────────────────────────────────────────────────────── #
    # TASK OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    async def create_task(
        self,
        session_id: str,
        title: str,
        description: str | None = None,
        needs_human_decision: bool = False,
    ) -> dict[str, Any] | None:
        """Cria uma nova task. Retorna None se a sessão não existe."""
        if not await self._exists_session(session_id):
            return None
        now = _now()
        order = await self._next_sort_order(session_id)
        res = await self._tasks.insert(
            {
                "session_id": session_id,
                "title": title,
                "description": description,
                "status": "pending",
                "sort_order": order,
                "needs_human_decision": 1 if needs_human_decision else 0,
                "created_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        await self._sessions.update_where(
            {"session_uid": session_id}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        return await self._task_row(int(res.returned_id)) if res.returned_id is not None else None

    async def create_tasks(
        self,
        session_id: str,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Cria várias tasks preservando a ordem. Retorna None se a sessão não existe."""
        if not tasks:
            return []
        if not await self._exists_session(session_id):
            return None
        now = _now()
        order = await self._next_sort_order(session_id)
        created: list[dict[str, Any]] = []
        for offset, item in enumerate(tasks):
            res = await self._tasks.insert(
                {
                    "session_id": session_id,
                    "title": item["title"],
                    "description": item.get("description"),
                    "status": "pending",
                    "sort_order": order + offset,
                    "needs_human_decision": 1 if item.get("needs_human_decision") else 0,
                    "created_at": now,
                },
                user_id=_SYSTEM_USER,
            )
            if res.returned_id is not None:
                row = await self._task_row(int(res.returned_id))
                if row is not None:
                    created.append(row)
        await self._sessions.update_where(
            {"session_uid": session_id}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        return created

    async def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Retorna uma task específica."""
        return await self._task_row(task_id)

    async def list_tasks(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]] | None:
        """Lista tasks de uma sessão. Retorna None se a sessão não existe."""
        if not await self._exists_session(session_id):
            return None
        conds: list[Any] = [_eq("session_id", session_id)]
        if status:
            conds.append(_eq("status", status))
        where = conds[0] if len(conds) == 1 else And(operands=conds)
        res = await self._tasks.find(
            where=where,
            order_by=[Sort(column="sort_order", direction=_ASC), Sort(column="id", direction=_ASC)],
        )
        return [_jsonable(r) for r in res.rows()]

    async def _transition_task(
        self,
        task_id: int,
        *,
        new_status: str,
        allowed_from: tuple[str, ...],
        result: str | None = None,
        commit_sha: str | None = None,
        commit_message: str | None = None,
        set_started_at: bool = False,
        set_completed_at: bool = False,
    ) -> dict[str, Any] | str | None:
        """Aplica transição de estado. Retorna a task atualizada, None se não existe,
        ou string com o estado atual quando a transição não é permitida."""
        row = await self._task_row(task_id)
        if row is None:
            return None
        if row["status"] not in allowed_from:
            return row["status"]
        now = _now()
        updates: dict[str, Any] = {"status": new_status}
        if set_started_at and not row.get("started_at"):
            updates["started_at"] = now
        if set_completed_at:
            updates["completed_at"] = now
        if result is not None:
            updates["result"] = result
        if commit_sha is not None:
            updates["commit_sha"] = commit_sha
        if commit_message is not None:
            updates["commit_message"] = commit_message
        await self._tasks.update_where({"id": task_id}, updates, user_id=_SYSTEM_USER)
        await self._sessions.update_where(
            {"session_uid": row["session_id"]}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        return await self._task_row(task_id)

    async def start_task(self, task_id: int) -> dict[str, Any] | str | None:
        """Marca task como in_progress (a partir de pending)."""
        return await self._transition_task(
            task_id,
            new_status="in_progress",
            allowed_from=("pending",),
            set_started_at=True,
        )

    async def complete_task(
        self,
        task_id: int,
        result: str | None = None,
        commit_sha: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any] | str | None:
        """Marca task como completed registrando o commit."""
        return await self._transition_task(
            task_id,
            new_status="completed",
            allowed_from=("pending", "in_progress"),
            result=result,
            commit_sha=commit_sha,
            commit_message=commit_message,
            set_started_at=True,
            set_completed_at=True,
        )

    async def fail_task(self, task_id: int, reason: str) -> dict[str, Any] | str | None:
        """Marca task como failed."""
        return await self._transition_task(
            task_id,
            new_status="failed",
            allowed_from=("pending", "in_progress"),
            result=reason,
            set_completed_at=True,
        )

    async def cancel_task(self, task_id: int, reason: str | None = None) -> dict[str, Any] | str | None:
        """Cancela task (de pending ou in_progress)."""
        return await self._transition_task(
            task_id,
            new_status="cancelled",
            allowed_from=("pending", "in_progress"),
            result=reason,
            set_completed_at=True,
        )

    async def approve_task(
        self,
        task_id: int,
        decision: str,
        notes: str | None = None,
    ) -> dict[str, Any] | str | None:
        """Registra decisão humana sobre uma task pendente.

        decision='go'    → marca decision='go'; a task fica pending mas liberada.
        decision='no_go' → cancela a task usando notes como reason.
        """
        row = await self._task_row(task_id)
        if row is None:
            return None
        if row["status"] != "pending":
            return row["status"]
        now = _now()
        if decision == "go":
            await self._tasks.update_where(
                {"id": task_id},
                {"decision": "go", "decided_at": now, "decision_notes": notes},
                user_id=_SYSTEM_USER,
            )
        elif decision == "no_go":
            await self._tasks.update_where(
                {"id": task_id},
                {
                    "decision": "no_go",
                    "decided_at": now,
                    "decision_notes": notes,
                    "status": "cancelled",
                    "completed_at": now,
                    "result": notes or "no_go (human decision)",
                },
                user_id=_SYSTEM_USER,
            )
        else:
            raise ValueError(f"decision inválida: '{decision}'")
        await self._sessions.update_where(
            {"session_uid": row["session_id"]}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        return await self._task_row(task_id)

    # ────────────────────────────────────────────────────────────────────────── #
    # SERVICE DEPENDENCY OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    async def add_service_dependency(
        self,
        session_id: str,
        service: str,
        role: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | str | None:
        """Vincula um serviço auxiliar à sessão.

        Retorna o registro criado, 'duplicate' se já vinculado (linha viva), ou None
        se a sessão não existe. Um serviço previamente removido (soft-delete) é
        REATIVADO via upsert pela chave natural (session_id, service).
        """
        if not await self._exists_session(session_id):
            return None
        if await self._service_row(session_id, service) is not None:
            return "duplicate"
        now = _now()
        await self._services.upsert(
            {
                "session_id": session_id,
                "service": service,
                "role": role,
                "notes": notes,
                "added_at": now,
            },
            conflict_columns=["session_id", "service"],
            user_id=_SYSTEM_USER,
        )
        await self._sessions.update_where(
            {"session_uid": session_id}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        row = await self._service_row(session_id, service)
        return _jsonable(row) if row else None

    async def list_service_dependencies(self, session_id: str) -> list[dict[str, Any]] | None:
        """Lista os serviços auxiliares. Retorna None se a sessão não existe."""
        if not await self._exists_session(session_id):
            return None
        return await self._list_service_deps(session_id)

    async def remove_service_dependency(self, session_id: str, service: str) -> bool | None:
        """Remove um vínculo (soft-delete). Retorna True se removeu, False se não
        existia (linha viva), None se a sessão não existe."""
        if not await self._exists_session(session_id):
            return None
        if await self._service_row(session_id, service) is None:
            return False
        now = _now()
        await self._services.delete_where(
            And(operands=[_eq("session_id", session_id), _eq("service", service)]),
            user_id=_SYSTEM_USER,
        )
        await self._sessions.update_where(
            {"session_uid": session_id}, {"last_updated_at": now}, user_id=_SYSTEM_USER
        )
        return True

    # ────────────────────────────────────────────────────────────────────────── #
    # SUGGESTION OPERATIONS
    # ────────────────────────────────────────────────────────────────────────── #

    async def create_suggestion(
        self,
        *,
        source_repo: str,
        target_repo: str,
        title: str,
        description: str | None = None,
        kind: str | None = None,
        priority: str | None = None,
        source_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Submete uma sugestão cross-repo."""
        now = _now()
        res = await self._suggestions.insert(
            {
                "source_repo": source_repo,
                "source_session_id": source_session_id,
                "target_repo": target_repo,
                "title": title,
                "description": description,
                "kind": kind,
                "priority": priority,
                "status": "pending",
                "created_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        row = await self._suggestion_row(int(res.returned_id)) if res.returned_id is not None else None
        return _jsonable(row) if row else {}

    async def get_suggestion(self, suggestion_id: int) -> dict[str, Any] | None:
        """Retorna uma sugestão pelo ID."""
        row = await self._suggestion_row(suggestion_id)
        return _jsonable(row) if row else None

    async def list_suggestions(
        self,
        target_repo: str | None = None,
        source_repo: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Lista sugestões com filtros opcionais."""
        conds: list[Any] = []
        if target_repo:
            conds.append(_eq("target_repo", target_repo))
        if source_repo:
            conds.append(_eq("source_repo", source_repo))
        if status:
            conds.append(_eq("status", status))
        where: Any = None
        if len(conds) == 1:
            where = conds[0]
        elif conds:
            where = And(operands=conds)
        res = await self._suggestions.find(
            where=where,
            order_by=[Sort(column="created_at", direction=_DESC), Sort(column="id", direction=_DESC)],
            limit=limit,
        )
        return [_jsonable(r) for r in res.rows()]

    async def count_pending_suggestions(self, target_repo: str) -> int:
        """Conta sugestões pendentes para um repositório."""
        return await self._suggestions.count(
            where=And(operands=[_eq("target_repo", target_repo), _eq("status", "pending")])
        )

    async def transition_suggestion(
        self,
        suggestion_id: int,
        *,
        new_status: str,
        allowed_from: tuple[str, ...] = ("pending",),
        response_reason: str | None = None,
        accepted_session_id: str | None = None,
        accepted_task_id: int | None = None,
        superseded_by: int | None = None,
    ) -> dict[str, Any] | str | None:
        """Aplica transição. Retorna registro atualizado, None se não existe,
        ou string com status atual se a transição é inválida."""
        row = await self._suggestion_row(suggestion_id)
        if row is None:
            return None
        if row["status"] not in allowed_from:
            return row["status"]
        now = _now()
        updates: dict[str, Any] = {"status": new_status, "responded_at": now}
        if response_reason is not None:
            updates["response_reason"] = response_reason
        if accepted_session_id is not None:
            updates["accepted_session_id"] = accepted_session_id
        if accepted_task_id is not None:
            updates["accepted_task_id"] = accepted_task_id
        if superseded_by is not None:
            updates["superseded_by"] = superseded_by
        await self._suggestions.update_where({"id": suggestion_id}, updates, user_id=_SYSTEM_USER)
        updated = await self._suggestion_row(suggestion_id)
        return _jsonable(updated) if updated else None

    # ────────────────────────────────────────────────────────────────────────── #
    # DECISION OPERATIONS (audit trail)
    # ────────────────────────────────────────────────────────────────────────── #

    async def record_decision(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        decision: str | None = None,
        rationale: str | None = None,
        context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Registra uma decisão no audit trail."""
        now = _now()
        ctx_json = json.dumps(context, ensure_ascii=False) if context else None
        res = await self._decisions.insert(
            {
                "actor_type": actor_type,
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "decision": decision,
                "rationale": rationale,
                "context_json": ctx_json,
                "session_id": session_id,
                "created_at": now,
            },
            user_id=_SYSTEM_USER,
        )
        row = await self._decision_row(int(res.returned_id)) if res.returned_id is not None else None
        return _jsonable(row) if row else {}

    async def list_decisions(
        self,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Lista o audit trail com filtros opcionais."""
        conds: list[Any] = []
        for col, val in (
            ("target_type", target_type),
            ("target_id", target_id),
            ("actor_type", actor_type),
            ("actor_id", actor_id),
            ("action", action),
            ("session_id", session_id),
        ):
            if val is not None:
                conds.append(_eq(col, val))
        where: Any = None
        if len(conds) == 1:
            where = conds[0]
        elif conds:
            where = And(operands=conds)
        res = await self._decisions.find(
            where=where, order_by=[Sort(column="id", direction=_DESC)], limit=limit
        )
        return [_jsonable(r) for r in res.rows()]

    async def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        """Retorna uma decisão pelo ID."""
        row = await self._decision_row(decision_id)
        return _jsonable(row) if row else None

    # ────────────────────────────────────────────────────────────────────────── #
    # RESUME
    # ────────────────────────────────────────────────────────────────────────── #

    async def get_resume_context(self, session_id: str) -> dict[str, Any] | None:
        """Retorna o contexto completo para retomar uma sessão."""
        row = await self._session_raw(session_id)
        if row is None:
            return None
        session = _jsonable(row)
        business = session.pop("session_uid", None)
        session["id"] = business

        cps = await self._checkpoints.find(
            where={"session_id": business},
            order_by=[Sort(column="id", direction=_DESC)],
            limit=5,
        )
        checkpoints = [_jsonable(c) for c in cps.rows()]

        arts = await self._artifacts.find(
            where={"session_id": business},
            order_by=[Sort(column="id", direction=_DESC)],
            limit=20,
        )
        artifacts = [_jsonable(a) for a in arts.rows()]

        open_rows = (
            await self._tasks.find(
                where=And(
                    operands=[
                        _eq("session_id", business),
                        Condition(column="status", op=Operator.IN, value=list(TASK_OPEN_STATUSES)),
                    ]
                ),
                order_by=[
                    Sort(column="sort_order", direction=_ASC),
                    Sort(column="id", direction=_ASC),
                ],
            )
        ).rows()
        open_tasks = [_jsonable(t) for t in open_rows]
        tasks_summary = await self._tasks_summary(business)

        service_deps = await self._list_service_deps(business)

        pending_suggestions: list[dict[str, Any]] = []
        pending_count = 0
        repo = session.get("repo")
        if repo:
            pending_count = await self.count_pending_suggestions(repo)
            pending_rows = await self._suggestions.find(
                where=And(operands=[_eq("target_repo", repo), _eq("status", "pending")]),
                order_by=[
                    Sort(column="created_at", direction=_DESC),
                    Sort(column="id", direction=_DESC),
                ],
                limit=5,
            )
            pending_suggestions = [_jsonable(r) for r in pending_rows.rows()]

        warnings: list[str] = []
        if not repo:
            warnings.append(
                "REPO_MISSING: sessão sem repositório dono. Use update_session "
                "para definir o repo antes de continuar — serviços auxiliares "
                "devem ser registrados via add_service_dependency consultando "
                "o services-mcp."
            )

        last_summary = checkpoints[0]["summary"] if checkpoints else "nenhum checkpoint salvo"
        name_part = f" [{session.get('name')}]" if session.get("name") else ""
        tasks_part = ""
        if open_tasks:
            titles = ", ".join(f"#{t['id']} {t['title']}" for t in open_tasks[:5])
            more = f" (+{len(open_tasks) - 5})" if len(open_tasks) > 5 else ""
            tasks_part = f" Tarefas abertas: {titles}{more}."
        services_part = ""
        if service_deps:
            names = ", ".join(s["service"] for s in service_deps[:5])
            more = f" (+{len(service_deps) - 5})" if len(service_deps) > 5 else ""
            services_part = f" Serviços auxiliares: {names}{more}."
        suggestions_part = ""
        if pending_count:
            titles = ", ".join(f"#{s['id']} {s['title']}" for s in pending_suggestions[:3])
            more = f" (+{pending_count - 3})" if pending_count > 3 else ""
            suggestions_part = f" Sugestões pendentes: {titles}{more}."
        warnings_part = ""
        if warnings:
            warnings_part = " ⚠ " + " ⚠ ".join(warnings)
        resume_hint = (
            f"Retomando sessão{name_part} '{session['title']}'. "
            f"Objetivo: {session['objective']}. "
            f"Repo: {session.get('repo') or 'não definido'}, "
            f"branch: {session.get('branch') or 'não definida'}. "
            f"Progresso atual: {session.get('progress') or 'não registrado'}. "
            f"Último checkpoint: {last_summary}."
            f"{tasks_part}"
            f"{services_part}"
            f"{suggestions_part}"
            f"{warnings_part}"
        )

        return {
            "session": session,
            "checkpoints": checkpoints,
            "recent_artifacts": artifacts,
            "open_tasks": open_tasks,
            "tasks_summary": tasks_summary,
            "service_dependencies": service_deps,
            "pending_suggestions": {
                "count": pending_count,
                "items": pending_suggestions,
            },
            "warnings": warnings,
            "resume_hint": resume_hint,
        }
