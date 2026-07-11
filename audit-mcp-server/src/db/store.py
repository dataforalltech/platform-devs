"""Store do audit-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do psycopg2 cru para o **Repository** de alto nível + Query IR, ligado ao
pool **do tenant** (resolvido credencial-zero via `for_tenant`/`get_pool_for_tenant`,
ORM-H-12). Roda dual-db: o mesmo código serve MySQL (banco-por-tenant) e PostgreSQL
(schema-por-tenant) — o dialeto do pool decide o SQL.

Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`update_where`/
`upsert`/`delete_where`). O blob JSON `checklist` (que aninhava items[] e approvals[])
foi NORMALIZADO em `audit_items` e `audit_approvals`. As operações que "não encaixam"
no CRUD trivial resolvem canonicamente:

  * auditoria por chave natural `audit_key`  -> `upsert(conflict_columns=["audit_key"])`
    (ON DUPLICATE KEY no MySQL / ON CONFLICT no PG); no re-audit a linha é sobrescrita
    "fresca" e os filhos (items/approvals) são soft-deletados — preservando a semântica
    do antigo `checklist={}` no create (que zerava items e approvals);
  * criticidade por chave natural `service`  -> `upsert(conflict_columns=["service"])`
    (implementa de verdade o antigo stub NO-OP; `get` cai em "medium" quando ausente);
  * items/approvals                          -> `insert` (append-only) + `find` filtrado.

O ``audit_id`` público continua sendo a STRING determinística ``audit_<service>_<env>``
(``audit_key``) — o ``id`` surrogate INT é interno; o round-trip expõe ``audit_key``
como ``id`` (contrato de string preservado p/ submit_audit_approval/get_audit_status/
get_audit_gate_result e o consumidor `audit_compliance` do pipeline-mcp).

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`) — os atores de negócio (approved_by/
updated_by/evaluated_by) continuam sendo strings em colunas próprias.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models.entities import (
    AuditApprovalRow,
    AuditItemRow,
    AuditRow,
    ServiceCriticalityRow,
)
from .schema import (
    AUDIT_APPROVALS_TABLE,
    AUDIT_ITEMS_TABLE,
    AUDITS_TABLE,
    SERVICE_CRITICALITY_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O ator de negócio real viaja em colunas próprias (approved_by, updated_by, ...).
_SYSTEM_USER = 0

# Criticidade default quando o serviço não tem linha em service_criticality.
_DEFAULT_CRITICALITY = "medium"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _audit_key(service: str, env: str) -> str:
    """Chave natural determinística — uma auditoria "corrente" por (service, env)."""
    return f"audit_{service}_{env}"


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Converte datetimes das colunas padrão (create_on/timestamp_refresh) em ISO str,
    para o `json.dumps` do envelope MCP não quebrar."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return out


def _shape_audit(row: dict[str, Any]) -> dict[str, Any]:
    """Forma canônica da linha de auditoria (back-compat):

    * ``id`` público = ``audit_key`` (string determinística; esconde o surrogate INT);
    * ``passed`` -> bool;
    * ``checklist`` JSON (TEXT) -> dict.
    """
    shaped = _jsonable(row)
    shaped["id"] = shaped.get("audit_key")
    shaped["passed"] = bool(shaped.get("passed"))
    checklist = shaped.get("checklist")
    if isinstance(checklist, str):
        try:
            shaped["checklist"] = json.loads(checklist)
        except (json.JSONDecodeError, TypeError):
            shaped["checklist"] = {}
    return shaped


def _shape_item(row: dict[str, Any]) -> dict[str, Any]:
    """Item do checklist na forma back-compat (required/passed como bool)."""
    return {
        "category": row.get("category"),
        "name": row.get("name"),
        "required": bool(row.get("required")),
        "passed": bool(row.get("passed")),
        "details": row.get("details"),
    }


def _shape_approval(row: dict[str, Any]) -> dict[str, Any]:
    """Aprovação na forma back-compat."""
    return {
        "approved_by": row.get("approved_by"),
        "role": row.get("role"),
        "decision": row.get("decision"),
        "notes": row.get("notes"),
        "created_at": row.get("created_at"),
    }


class AuditStore:
    """Store tenant-scoped: 4 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._audits = session.repository(AuditRow, table_name=AUDITS_TABLE)
        self._items = session.repository(AuditItemRow, table_name=AUDIT_ITEMS_TABLE)
        self._approvals = session.repository(AuditApprovalRow, table_name=AUDIT_APPROVALS_TABLE)
        self._criticality = session.repository(ServiceCriticalityRow, table_name=SERVICE_CRITICALITY_TABLE)

    # -- helpers de leitura ---------------------------------------------------- #

    async def _audit_row(self, audit_id: str) -> dict[str, Any] | None:
        res = await self._audits.find(where={"audit_key": audit_id}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    # -- Auditorias ------------------------------------------------------------ #

    async def create_audit(
        self,
        service: str,
        repo: str,
        env: str,
        criticality: str,
        score: float,
        passed: bool,
        status: str,
        checklist: dict[str, Any],
    ) -> str:
        """Cria (ou sobrescreve, no re-audit) a auditoria corrente de (service, env).

        Retorna o ``audit_id`` público (string ``audit_<service>_<env>``). Zera os
        filhos (items/approvals) para o comportamento "auditoria fresca" do antigo
        ``checklist={}`` no create.
        """
        key = _audit_key(service, env)
        now = _now()
        # Auditoria fresca: solta os filhos da auditoria anterior (soft-delete canônico).
        await self._items.delete_where({"audit_id": key}, user_id=_SYSTEM_USER)
        await self._approvals.delete_where({"audit_id": key}, user_id=_SYSTEM_USER)
        await self._audits.upsert(
            {
                "audit_key": key,
                "service": service,
                "repo": repo,
                "env": env,
                "criticality": criticality,
                "score": score,
                "passed": 1 if passed else 0,
                "status": status,
                "checklist": json.dumps(checklist),
                "created_at": now,
                "updated_at": now,
            },
            conflict_columns=["audit_key"],
            user_id=_SYSTEM_USER,
        )
        return key

    async def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        """Retorna uma auditoria específica (por audit_id string)."""
        row = await self._audit_row(audit_id)
        return _shape_audit(row) if row else None

    async def get_latest_audit(self, service: str, env: str) -> dict[str, Any] | None:
        """Retorna a auditoria corrente de um serviço/ambiente (a mais recente)."""
        res = await self._audits.find(
            where={"service": service, "env": env},
            order_by=[Sort(column="created_at", direction=SortDirection.DESC)],
            limit=1,
        )
        rows = res.rows()
        return _shape_audit(rows[0]) if rows else None

    async def list_audits(
        self,
        status: str | None = None,
        env: str | None = None,
        service: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lista auditorias com filtros opcionais (ordenadas por data decrescente)."""
        where: dict[str, Any] = {}
        if status:
            where["status"] = status
        if env:
            where["env"] = env
        if service:
            where["service"] = service
        res = await self._audits.find(
            where=where or None,
            order_by=[Sort(column="created_at", direction=SortDirection.DESC)],
            limit=limit,
            offset=offset,
        )
        return [_shape_audit(r) for r in res.rows()]

    async def update_audit_status(self, audit_id: str, status: str, score: float, passed: bool) -> None:
        """Atualiza status/score/passed de uma auditoria."""
        await self._audits.update_where(
            {"audit_key": audit_id},
            {"status": status, "score": score, "passed": 1 if passed else 0, "updated_at": _now()},
            user_id=_SYSTEM_USER,
        )

    # -- Itens do checklist (tabela normalizada) ------------------------------- #

    async def add_audit_item(
        self,
        audit_id: str,
        category: str,
        name: str,
        required: bool,
        passed: bool,
        details: str | None = None,
    ) -> None:
        """Adiciona um item de auditoria (tabela `audit_items`, antes JSON aninhado)."""
        await self._items.insert(
            {
                "audit_id": audit_id,
                "category": category,
                "name": name,
                "required": 1 if required else 0,
                "passed": 1 if passed else 0,
                "details": details,
            },
            user_id=_SYSTEM_USER,
        )

    async def get_audit_items(self, audit_id: str) -> list[dict[str, Any]]:
        """Retorna items de uma auditoria."""
        res = await self._items.find(
            where={"audit_id": audit_id},
            order_by=[
                Sort(column="category", direction=SortDirection.ASC),
                Sort(column="name", direction=SortDirection.ASC),
            ],
        )
        return [_shape_item(r) for r in res.rows()]

    # -- Aprovações (tabela normalizada) --------------------------------------- #

    async def add_approval(
        self,
        audit_id: str,
        approved_by: str,
        decision: str,
        role: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Registra uma aprovação/rejeição (tabela `audit_approvals`)."""
        await self._approvals.insert(
            {
                "audit_id": audit_id,
                "approved_by": approved_by,
                "role": role,
                "decision": decision,
                "notes": notes,
                "created_at": _now(),
            },
            user_id=_SYSTEM_USER,
        )

    async def get_approvals(self, audit_id: str) -> list[dict[str, Any]]:
        """Retorna aprovações de uma auditoria (mais recentes primeiro)."""
        res = await self._approvals.find(
            where={"audit_id": audit_id},
            order_by=[Sort(column="created_at", direction=SortDirection.DESC)],
        )
        return [_shape_approval(r) for r in res.rows()]

    # -- Criticidade por serviço (antes um stub NO-OP) ------------------------- #

    async def set_service_criticality(self, service: str, criticality: str, updated_by: str) -> None:
        """Define a criticidade de um serviço (upsert na chave natural `service`)."""
        await self._criticality.upsert(
            {
                "service": service,
                "criticality": criticality,
                "updated_by": updated_by,
                "updated_at": _now(),
            },
            conflict_columns=["service"],
            user_id=_SYSTEM_USER,
        )

    async def get_service_criticality(self, service: str) -> str:
        """Retorna a criticidade do serviço (default "medium" quando não definida)."""
        res = await self._criticality.find(where={"service": service}, limit=1)
        rows = res.rows()
        crit = rows[0].get("criticality") if rows else None
        return crit or _DEFAULT_CRITICALITY
