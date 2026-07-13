"""Store do devops-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 5
entidades do persona (artefatos IaC/pipelines/deployments/environments/service
configs). Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`update`/
`update_where`/`upsert`/`delete_where`). As chaves naturais são `name` (environment) e
`service` (service config) — upsert; o resto é histórico com chave surrogate `id` e
soft-delete canônico.

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
    DeploymentRow,
    DevopsArtifactRow,
    EnvironmentRow,
    PipelineRow,
    ServiceConfigRow,
)
from .schema import (
    ARTIFACTS_TABLE,
    DEPLOYMENTS_TABLE,
    ENVIRONMENTS_TABLE,
    PIPELINES_TABLE,
    SERVICE_CONFIGS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    ARTIFACTS_TABLE: ("spec",),
    PIPELINES_TABLE: ("content",),
    DEPLOYMENTS_TABLE: ("meta",),
    ENVIRONMENTS_TABLE: ("config",),
    SERVICE_CONFIGS_TABLE: ("settings",),
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
    chaves naturais (``name`` em environments, ``service`` em service_configs) são sempre
    não-``None``, então nunca são podadas.
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


class DevopsStore:
    """Store tenant-scoped: 5 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._artifacts = session.repository(DevopsArtifactRow, table_name=ARTIFACTS_TABLE)
        self._pipelines = session.repository(PipelineRow, table_name=PIPELINES_TABLE)
        self._deployments = session.repository(DeploymentRow, table_name=DEPLOYMENTS_TABLE)
        self._environments = session.repository(EnvironmentRow, table_name=ENVIRONMENTS_TABLE)
        self._configs = session.repository(ServiceConfigRow, table_name=SERVICE_CONFIGS_TABLE)

    # -- helpers de leitura (por id / por chave natural) ----------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- Artifacts (histórico append-only) ------------------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: str,
        tool: str | None = None,
        spec: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
                "tool": tool,
                "content": content,
                "spec": _dumps(spec),
                "status": status,
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

    # -- Pipelines ------------------------------------------------------------- #

    async def save_pipeline(
        self,
        application: str,
        provider: str,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._pipelines.insert(
            {
                "application": application,
                "provider": provider,
                "content": _dumps(content),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._pipelines, new_id, _JSON_FIELDS[PIPELINES_TABLE])
        return row or {}

    async def list_pipelines(
        self, application: str | None = None, provider: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if application:
            where["application"] = application
        if provider:
            where["provider"] = provider
        if status:
            where["status"] = status
        res = await self._pipelines.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[PIPELINES_TABLE]) for r in res.rows()]

    async def get_pipeline(self, pipeline_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._pipelines, pipeline_id, _JSON_FIELDS[PIPELINES_TABLE])

    async def update_pipeline(
        self,
        pipeline_id: int,
        provider: str | None = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if provider is not None:
            changes["provider"] = provider
        if content is not None:
            changes["content"] = _dumps(content)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._pipelines.update(pipeline_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._pipelines, pipeline_id, _JSON_FIELDS[PIPELINES_TABLE])

    async def delete_pipeline(self, pipeline_id: int) -> int:
        res = await self._pipelines.delete_where({"id": pipeline_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Deployments ----------------------------------------------------------- #

    async def save_deployment(
        self,
        application: str,
        environment: str,
        version: str,
        strategy: str | None = None,
        notes: str | None = None,
        meta: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._deployments.insert(
            {
                "application": application,
                "environment": environment,
                "version": version,
                "strategy": strategy,
                "notes": notes,
                "meta": _dumps(meta),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._deployments, new_id, _JSON_FIELDS[DEPLOYMENTS_TABLE])
        return row or {}

    async def list_deployments(
        self,
        application: str | None = None,
        environment: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if application:
            where["application"] = application
        if environment:
            where["environment"] = environment
        if status:
            where["status"] = status
        res = await self._deployments.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[DEPLOYMENTS_TABLE]) for r in res.rows()]

    async def get_deployment(self, deployment_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._deployments, deployment_id, _JSON_FIELDS[DEPLOYMENTS_TABLE])

    async def update_deployment_status(self, deployment_id: int, status: str) -> dict[str, Any] | None:
        await self._deployments.update(deployment_id, {"status": status}, user_id=_SYSTEM_USER)
        return await self._by_id(self._deployments, deployment_id, _JSON_FIELDS[DEPLOYMENTS_TABLE])

    async def delete_deployment(self, deployment_id: int) -> int:
        res = await self._deployments.delete_where({"id": deployment_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Environments (upsert por chave natural `name`) ------------------------ #

    async def _env_by_name(self, name: str) -> dict[str, Any] | None:
        res = await self._environments.find(where={"name": name}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[ENVIRONMENTS_TABLE]) if rows else None

    async def set_environment(
        self,
        name: str,
        kind: str,
        region: str | None = None,
        config: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._environments.upsert(
            _prune(
                {
                    "name": name,
                    "kind": kind,
                    "region": region,
                    "config": _dumps(config),
                    "status": status,
                }
            ),
            conflict_columns=["name"],
            user_id=_SYSTEM_USER,
        )
        row = await self._env_by_name(name)
        return row or {}

    async def list_environments(
        self, kind: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if kind:
            where["kind"] = kind
        if status:
            where["status"] = status
        res = await self._environments.find(
            where=where or None,
            order_by=[Sort(column="name", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[ENVIRONMENTS_TABLE]) for r in res.rows()]

    async def get_environment(self, name: str) -> dict[str, Any] | None:
        return await self._env_by_name(name)

    async def delete_environment(self, name: str) -> int:
        res = await self._environments.delete_where({"name": name}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Service Configs (upsert por chave natural `service`) ------------------ #

    async def _config_by_service(self, service: str) -> dict[str, Any] | None:
        res = await self._configs.find(where={"service": service}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[SERVICE_CONFIGS_TABLE]) if rows else None

    async def set_service_config(
        self, service: str, settings: Any, status: str | None = None
    ) -> dict[str, Any]:
        await self._configs.upsert(
            _prune(
                {
                    "service": service,
                    "settings": _dumps(settings),
                    "status": status,
                }
            ),
            conflict_columns=["service"],
            user_id=_SYSTEM_USER,
        )
        row = await self._config_by_service(service)
        return row or {}

    async def list_service_configs(self, status: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if status:
            where["status"] = status
        res = await self._configs.find(
            where=where or None,
            order_by=[Sort(column="service", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[SERVICE_CONFIGS_TABLE]) for r in res.rows()]

    async def get_service_config(self, service: str) -> dict[str, Any] | None:
        return await self._config_by_service(service)

    async def delete_service_config(self, service: str) -> int:
        res = await self._configs.delete_where({"service": service}, user_id=_SYSTEM_USER)
        return res.rowcount
