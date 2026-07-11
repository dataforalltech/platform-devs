"""Store do qa-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do psycopg2 cru para o **Repository** de alto nível, ligado ao pool **do
tenant** (resolvido credencial-zero via `for_tenant`/`get_pool_for_tenant`, ORM-H-12).
Roda dual-db: o mesmo código serve MySQL (banco-por-tenant) e PostgreSQL (schema-por-
tenant) — o dialeto do pool decide o SQL.

O `test_runs` é um log append-only, então o store expõe só Create + Read (a superfície
original, preservada 1:1):

  * ``save_run``  -> `Repository.insert` (INSERT; `started_at` = agora UTC ISO;
    summary/details serializados em JSON; retorna o id gerado).
  * ``list_runs`` -> `Repository.find` (SELECT com filtros opcionais, ORDER BY
    started_at DESC, LIMIT; summary/details desserializados; datetimes -> ISO).

Sem SQL manual, sem pool/lock/migração próprios (o schema é bootstrapped por
`db.schema.ensure_schema` 1x por tenant). Convenções: `PLATFORM_CONVENTIONS` (soft-
delete `excluded=0`, auditoria `id_user_*`/`timestamp_refresh`). Como `id_user_created`
é NOT NULL sem default, todo write carimba o usuário-sistema (`_SYSTEM_USER`).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models import TestRunRow
from .schema import TEST_RUNS_TABLE

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# As execuções de QA não têm um "ator" de negócio persistido (governança só).
_SYSTEM_USER = 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Converte datetimes das colunas padrão (create_on/timestamp_refresh) em ISO str,
    para o `json.dumps` do envelope MCP não quebrar."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return out


def _shape_run(row: dict[str, Any]) -> dict[str, Any]:
    """Forma canônica da linha de run: datetimes -> ISO, summary/details JSON -> dict."""
    shaped = _jsonable(row)
    for field in ("summary", "details"):
        value = shaped.get(field)
        if isinstance(value, str):
            try:
                shaped[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                shaped[field] = {}
    return shaped


class QAStore:
    """Store tenant-scoped: um repositório ligado ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria o
    repositório canônico por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._runs = session.repository(TestRunRow, table_name=TEST_RUNS_TABLE)

    async def save_run(
        self,
        run_type: str,
        status: str,
        summary: dict,
        details: dict,
        repo_path: str | None = None,
        framework: str | None = None,
        duration_ms: int | None = None,
    ) -> int:
        """Grava UMA execução no histórico e retorna o id gerado."""
        res = await self._runs.insert(
            {
                "repo_path": repo_path,
                "run_type": run_type,
                "framework": framework,
                "started_at": _now(),
                "duration_ms": duration_ms,
                "status": status,
                "summary": json.dumps(summary),
                "details": json.dumps(details),
            },
            user_id=_SYSTEM_USER,
        )
        return int(res.returned_id) if res.returned_id is not None else 0

    async def list_runs(
        self,
        repo_path: str | None = None,
        run_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Consulta o histórico (filtros opcionais), mais recentes primeiro."""
        where: dict[str, Any] = {}
        if repo_path:
            where["repo_path"] = repo_path
        if run_type:
            where["run_type"] = run_type
        res = await self._runs.find(
            where=where or None,
            order_by=[
                Sort(column="started_at", direction=SortDirection.DESC),
                Sort(column="id", direction=SortDirection.DESC),
            ],
            limit=limit,
        )
        return [_shape_run(r) for r in res.rows()]
