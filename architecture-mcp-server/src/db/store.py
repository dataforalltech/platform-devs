"""Store do architecture-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 4
entidades do persona (propostas de arquitetura / modelos C4 / blueprints de solução /
artefatos). Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/
`update`/`update_where`/`upsert`/`delete_where`). A ÚNICA chave natural é
`system_name` no modelo C4 (upsert por sistema); o resto é histórico com chave
surrogate `id` e soft-delete canônico.

Dados estruturados viajam como dict/list na API e são serializados em JSON (TEXT) na
persistência (dual-db safe). Convenções: `PLATFORM_CONVENTIONS` (soft-delete
`excluded=0`, auditoria `id_user_*`/`timestamp_refresh`). Como `id_user_created` é
NOT NULL sem default, todo write carimba o usuário-sistema (`_SYSTEM_USER`).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from platform_database.orm import Sort, SortDirection

from ..models import (
    ArchitectureArtifactRow,
    ArchitectureBlueprintRow,
    C4DiagramRow,
    SolutionBlueprintRow,
)
from .schema import (
    ARCHITECTURE_BLUEPRINTS_TABLE,
    ARTIFACTS_TABLE,
    C4_DIAGRAMS_TABLE,
    SOLUTION_BLUEPRINTS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    ARCHITECTURE_BLUEPRINTS_TABLE: ("constraints", "quality_attributes", "content"),
    C4_DIAGRAMS_TABLE: ("model",),
    SOLUTION_BLUEPRINTS_TABLE: ("content",),
    ARTIFACTS_TABLE: ("meta",),
}


def _dumps(value: Any) -> str | None:
    """Serializa dict/list em JSON (TEXT). ``None`` permanece ``None`` (coluna NULL)."""
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _prune(record: dict[str, Any]) -> dict[str, Any]:
    """Payload de upsert com semântica de *merge*: descarta as chaves com valor ``None``.

    O ``upsert`` do ORM deriva o ``SET`` do ON DUPLICATE KEY UPDATE de TODAS as colunas
    não-chave presentes no payload (``update_columns=None``). Se um campo omitido viajar
    como ``None``, o update-path o sobrescreve com ``NULL``, apagando o valor já gravado
    numa chamada anterior. Podando os ``None`` antes do upsert, só as colunas fornecidas
    entram no INSERT e no ``SET`` — os campos omitidos preservam o valor persistido. A
    chave natural (``system_name``) é sempre não-``None``, então nunca é podada.
    """
    return {k: v for k, v in record.items() if v is not None}


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Datetimes das colunas padrão (create_on/timestamp_refresh) -> ISO str, para o
    `json.dumps` do envelope MCP não quebrar."""
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in row.items()}


def _shape(row: dict[str, Any], json_fields: tuple[str, ...]) -> dict[str, Any]:
    """Forma canônica de uma linha: datetimes -> ISO, campos JSON (TEXT) -> dict/list."""
    shaped = _jsonable(row)
    for field in json_fields:
        value = shaped.get(field)
        if isinstance(value, str):
            try:
                shaped[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                shaped[field] = None
    return shaped


class ArchitectureStore:
    """Store tenant-scoped: 4 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._blueprints = session.repository(
            ArchitectureBlueprintRow, table_name=ARCHITECTURE_BLUEPRINTS_TABLE
        )
        self._c4 = session.repository(C4DiagramRow, table_name=C4_DIAGRAMS_TABLE)
        self._solutions = session.repository(SolutionBlueprintRow, table_name=SOLUTION_BLUEPRINTS_TABLE)
        self._artifacts = session.repository(ArchitectureArtifactRow, table_name=ARTIFACTS_TABLE)

    # -- helpers de leitura (por id / por chave natural) ----------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- Architecture Blueprints (proposta de arquitetura) --------------------- #

    async def save_architecture_blueprint(
        self,
        name: str,
        domain: str,
        style: str | None = None,
        constraints: Any = None,
        quality_attributes: Any = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._blueprints.insert(
            {
                "name": name,
                "domain": domain,
                "style": style,
                "constraints": _dumps(constraints),
                "quality_attributes": _dumps(quality_attributes),
                "content": _dumps(content),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._blueprints, new_id, _JSON_FIELDS[ARCHITECTURE_BLUEPRINTS_TABLE])
        return row or {}

    async def list_architecture_blueprints(
        self, domain: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if domain:
            where["domain"] = domain
        if status:
            where["status"] = status
        res = await self._blueprints.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[ARCHITECTURE_BLUEPRINTS_TABLE]) for r in res.rows()]

    async def get_architecture_blueprint(self, blueprint_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._blueprints, blueprint_id, _JSON_FIELDS[ARCHITECTURE_BLUEPRINTS_TABLE])

    async def update_architecture_blueprint(
        self,
        blueprint_id: int,
        name: str | None = None,
        style: str | None = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name
        if style is not None:
            changes["style"] = style
        if content is not None:
            changes["content"] = _dumps(content)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._blueprints.update(blueprint_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._blueprints, blueprint_id, _JSON_FIELDS[ARCHITECTURE_BLUEPRINTS_TABLE])

    async def delete_architecture_blueprint(self, blueprint_id: int) -> int:
        res = await self._blueprints.delete_where({"id": blueprint_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- C4 Diagrams (upsert por chave natural `system_name`) ------------------ #

    async def _c4_by_system(self, system_name: str) -> dict[str, Any] | None:
        res = await self._c4.find(where={"system_name": system_name}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[C4_DIAGRAMS_TABLE]) if rows else None

    async def set_c4_diagram(
        self,
        system_name: str,
        model: Any,
        title: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._c4.upsert(
            _prune(
                {
                    "system_name": system_name,
                    "title": title,
                    "model": _dumps(model),
                    "status": status,
                }
            ),
            conflict_columns=["system_name"],
            user_id=_SYSTEM_USER,
        )
        row = await self._c4_by_system(system_name)
        return row or {}

    async def list_c4_diagrams(self, status: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if status:
            where["status"] = status
        res = await self._c4.find(
            where=where or None,
            order_by=[Sort(column="system_name", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[C4_DIAGRAMS_TABLE]) for r in res.rows()]

    async def get_c4_diagram(self, system_name: str) -> dict[str, Any] | None:
        return await self._c4_by_system(system_name)

    async def delete_c4_diagram(self, system_name: str) -> int:
        res = await self._c4.delete_where({"system_name": system_name}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Solution Blueprints (histórico) --------------------------------------- #

    async def save_solution_blueprint(
        self,
        solution_name: str,
        content: Any,
        context: str | None = None,
        requirements: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._solutions.insert(
            {
                "solution_name": solution_name,
                "context": context,
                "requirements": requirements,
                "content": _dumps(content),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._solutions, new_id, _JSON_FIELDS[SOLUTION_BLUEPRINTS_TABLE])
        return row or {}

    async def list_solution_blueprints(
        self, solution_name: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if solution_name:
            where["solution_name"] = solution_name
        if status:
            where["status"] = status
        res = await self._solutions.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[SOLUTION_BLUEPRINTS_TABLE]) for r in res.rows()]

    async def get_solution_blueprint(self, blueprint_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._solutions, blueprint_id, _JSON_FIELDS[SOLUTION_BLUEPRINTS_TABLE])

    async def update_solution_blueprint(
        self,
        blueprint_id: int,
        context: str | None = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if context is not None:
            changes["context"] = context
        if content is not None:
            changes["content"] = _dumps(content)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._solutions.update(blueprint_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._solutions, blueprint_id, _JSON_FIELDS[SOLUTION_BLUEPRINTS_TABLE])

    async def delete_solution_blueprint(self, blueprint_id: int) -> int:
        res = await self._solutions.delete_where({"id": blueprint_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Artifacts (histórico append-only) ------------------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: str,
        format: str | None = None,
        meta: Any = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
                "format": format,
                "content": content,
                "meta": _dumps(meta),
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._artifacts, new_id, _JSON_FIELDS[ARTIFACTS_TABLE])
        return row or {}

    async def list_artifacts(
        self, kind: str | None = None, target: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if kind:
            where["kind"] = kind
        if target:
            where["target"] = target
        res = await self._artifacts.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
            limit=limit,
        )
        return [_shape(r, _JSON_FIELDS[ARTIFACTS_TABLE]) for r in res.rows()]

    async def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._artifacts, artifact_id, _JSON_FIELDS[ARTIFACTS_TABLE])

    async def delete_artifact(self, artifact_id: int) -> int:
        res = await self._artifacts.delete_where({"id": artifact_id}, user_id=_SYSTEM_USER)
        return res.rowcount
