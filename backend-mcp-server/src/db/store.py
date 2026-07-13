"""Store do backend-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 5
entidades do persona (contratos de API/schemas de banco/políticas de auth/artefatos
de código/reviews). Sem SQL manual: cada read/write cai no Repository (`find`/
`insert`/`update`/`update_where`/`upsert`/`delete_where`). As chaves naturais são
`(endpoint, method)` no contrato de API e `resource` na política de auth (ambas com
upsert); o resto é histórico com chave surrogate `id` e soft-delete canônico.

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
    APIContractRow,
    AuthPolicyRow,
    BackendArtifactRow,
    CodeReviewRow,
    DatabaseSchemaRow,
)
from .schema import (
    API_CONTRACTS_TABLE,
    ARTIFACTS_TABLE,
    AUTH_POLICIES_TABLE,
    CODE_REVIEWS_TABLE,
    DATABASE_SCHEMAS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    API_CONTRACTS_TABLE: ("request_schema", "response_schema", "status_codes"),
    DATABASE_SCHEMAS_TABLE: ("attributes", "relationships", "indexes", "constraints"),
    AUTH_POLICIES_TABLE: ("roles", "rules"),
    ARTIFACTS_TABLE: ("meta",),
    CODE_REVIEWS_TABLE: ("focus", "findings"),
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
    entram no INSERT e no ``SET`` — os campos omitidos preservam o valor persistido. As
    chaves naturais (``endpoint``+``method`` em api_contracts, ``resource`` em
    auth_policies) são sempre não-``None``, então nunca são podadas.
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


class BackendStore:
    """Store tenant-scoped: 5 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._contracts = session.repository(APIContractRow, table_name=API_CONTRACTS_TABLE)
        self._schemas = session.repository(DatabaseSchemaRow, table_name=DATABASE_SCHEMAS_TABLE)
        self._policies = session.repository(AuthPolicyRow, table_name=AUTH_POLICIES_TABLE)
        self._artifacts = session.repository(BackendArtifactRow, table_name=ARTIFACTS_TABLE)
        self._reviews = session.repository(CodeReviewRow, table_name=CODE_REVIEWS_TABLE)

    # -- helpers de leitura (por id) ------------------------------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- API Contracts (upsert por chave natural composta endpoint+method) ----- #

    async def _contract_by_key(self, endpoint: str, method: str) -> dict[str, Any] | None:
        res = await self._contracts.find(where={"endpoint": endpoint, "method": method}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[API_CONTRACTS_TABLE]) if rows else None

    async def save_api_contract(
        self,
        endpoint: str,
        method: str,
        description: str | None = None,
        request_schema: Any = None,
        response_schema: Any = None,
        status_codes: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._contracts.upsert(
            _prune(
                {
                    "endpoint": endpoint,
                    "method": method,
                    "description": description,
                    "request_schema": _dumps(request_schema),
                    "response_schema": _dumps(response_schema),
                    "status_codes": _dumps(status_codes),
                    "status": status,
                }
            ),
            conflict_columns=["endpoint", "method"],
            user_id=_SYSTEM_USER,
        )
        row = await self._contract_by_key(endpoint, method)
        return row or {}

    async def list_api_contracts(
        self, endpoint: str | None = None, method: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if endpoint:
            where["endpoint"] = endpoint
        if method:
            where["method"] = method
        if status:
            where["status"] = status
        res = await self._contracts.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[API_CONTRACTS_TABLE]) for r in res.rows()]

    async def get_api_contract(self, endpoint: str, method: str) -> dict[str, Any] | None:
        return await self._contract_by_key(endpoint, method)

    async def delete_api_contract(self, endpoint: str, method: str) -> int:
        res = await self._contracts.delete_where(
            {"endpoint": endpoint, "method": method}, user_id=_SYSTEM_USER
        )
        return res.rowcount

    # -- Database Schemas (histórico, chave surrogate id) ---------------------- #

    async def save_database_schema(
        self,
        entity: str,
        database_name: str,
        attributes: Any = None,
        relationships: Any = None,
        indexes: Any = None,
        constraints: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._schemas.insert(
            {
                "entity": entity,
                "database_name": database_name,
                "attributes": _dumps(attributes),
                "relationships": _dumps(relationships),
                "indexes": _dumps(indexes),
                "constraints": _dumps(constraints),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._schemas, new_id, _JSON_FIELDS[DATABASE_SCHEMAS_TABLE])
        return row or {}

    async def list_database_schemas(
        self, entity: str | None = None, database_name: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if entity:
            where["entity"] = entity
        if database_name:
            where["database_name"] = database_name
        if status:
            where["status"] = status
        res = await self._schemas.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[DATABASE_SCHEMAS_TABLE]) for r in res.rows()]

    async def get_database_schema(self, schema_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._schemas, schema_id, _JSON_FIELDS[DATABASE_SCHEMAS_TABLE])

    async def update_database_schema(
        self,
        schema_id: int,
        database_name: str | None = None,
        attributes: Any = None,
        relationships: Any = None,
        indexes: Any = None,
        constraints: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if database_name is not None:
            changes["database_name"] = database_name
        if attributes is not None:
            changes["attributes"] = _dumps(attributes)
        if relationships is not None:
            changes["relationships"] = _dumps(relationships)
        if indexes is not None:
            changes["indexes"] = _dumps(indexes)
        if constraints is not None:
            changes["constraints"] = _dumps(constraints)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._schemas.update(schema_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._schemas, schema_id, _JSON_FIELDS[DATABASE_SCHEMAS_TABLE])

    async def delete_database_schema(self, schema_id: int) -> int:
        res = await self._schemas.delete_where({"id": schema_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Auth Policies (upsert por chave natural `resource`) ------------------- #

    async def _policy_by_resource(self, resource: str) -> dict[str, Any] | None:
        res = await self._policies.find(where={"resource": resource}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[AUTH_POLICIES_TABLE]) if rows else None

    async def save_auth_policy(
        self,
        resource: str,
        auth_type: str,
        roles: Any = None,
        data_sensitivity: str | None = None,
        rules: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._policies.upsert(
            _prune(
                {
                    "resource": resource,
                    "auth_type": auth_type,
                    "roles": _dumps(roles),
                    "data_sensitivity": data_sensitivity,
                    "rules": _dumps(rules),
                    "status": status,
                }
            ),
            conflict_columns=["resource"],
            user_id=_SYSTEM_USER,
        )
        row = await self._policy_by_resource(resource)
        return row or {}

    async def list_auth_policies(
        self, auth_type: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if auth_type:
            where["auth_type"] = auth_type
        if status:
            where["status"] = status
        res = await self._policies.find(
            where=where or None,
            order_by=[Sort(column="resource", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[AUTH_POLICIES_TABLE]) for r in res.rows()]

    async def get_auth_policy(self, resource: str) -> dict[str, Any] | None:
        return await self._policy_by_resource(resource)

    async def delete_auth_policy(self, resource: str) -> int:
        res = await self._policies.delete_where({"resource": resource}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Backend Artifacts (histórico append-only) ----------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: str,
        language: str | None = None,
        framework: str | None = None,
        meta: Any = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
                "language": language,
                "framework": framework,
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

    # -- Code Reviews (histórico append-only) ---------------------------------- #

    async def save_code_review(
        self,
        target: str,
        language: str,
        focus: Any = None,
        findings: Any = None,
        security_score: float | None = None,
        performance_score: float | None = None,
        summary: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._reviews.insert(
            {
                "target": target,
                "language": language,
                "focus": _dumps(focus),
                "findings": _dumps(findings),
                "security_score": security_score,
                "performance_score": performance_score,
                "summary": summary,
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._reviews, new_id, _JSON_FIELDS[CODE_REVIEWS_TABLE])
        return row or {}

    async def list_code_reviews(
        self, target: str | None = None, language: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if target:
            where["target"] = target
        if language:
            where["language"] = language
        if status:
            where["status"] = status
        res = await self._reviews.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[CODE_REVIEWS_TABLE]) for r in res.rows()]

    async def get_code_review(self, review_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._reviews, review_id, _JSON_FIELDS[CODE_REVIEWS_TABLE])

    async def delete_code_review(self, review_id: int) -> int:
        res = await self._reviews.delete_where({"id": review_id}, user_id=_SYSTEM_USER)
        return res.rowcount
