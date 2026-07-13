"""Store do security-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 4
entidades do persona (threat models/controles/avaliações CVSS/artefatos). Sem SQL
manual: cada read/write cai no Repository (`find`/`insert`/`update`/`update_where`/
`upsert`/`delete_where`). A ÚNICA chave natural é `(system_name, control_key)` no controle
(upsert por sistema+chave); o resto é histórico com chave surrogate `id` e soft-delete
canônico.

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
    CvssAssessmentRow,
    SecurityArtifactRow,
    SecurityControlRow,
    ThreatModelRow,
)
from .schema import (
    ARTIFACTS_TABLE,
    CVSS_ASSESSMENTS_TABLE,
    SECURITY_CONTROLS_TABLE,
    THREAT_MODELS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    THREAT_MODELS_TABLE: ("components", "threats"),
    SECURITY_CONTROLS_TABLE: ("details",),
    CVSS_ASSESSMENTS_TABLE: ("metrics",),
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
    chave natural composta (``system_name``+``control_key``) é sempre não-``None``, então
    nunca é podada.
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


class SecurityStore:
    """Store tenant-scoped: 4 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._threats = session.repository(ThreatModelRow, table_name=THREAT_MODELS_TABLE)
        self._controls = session.repository(SecurityControlRow, table_name=SECURITY_CONTROLS_TABLE)
        self._cvss = session.repository(CvssAssessmentRow, table_name=CVSS_ASSESSMENTS_TABLE)
        self._artifacts = session.repository(SecurityArtifactRow, table_name=ARTIFACTS_TABLE)

    # -- helpers de leitura (por id) ------------------------------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- Threat Models --------------------------------------------------------- #

    async def save_threat_model(
        self,
        system_name: str,
        methodology: str = "STRIDE",
        title: str | None = None,
        components: Any = None,
        threats: Any = None,
        summary: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._threats.insert(
            {
                "system_name": system_name,
                "methodology": methodology,
                "title": title,
                "components": _dumps(components),
                "threats": _dumps(threats),
                "summary": summary,
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._threats, new_id, _JSON_FIELDS[THREAT_MODELS_TABLE])
        return row or {}

    async def list_threat_models(
        self, system_name: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if system_name:
            where["system_name"] = system_name
        if status:
            where["status"] = status
        res = await self._threats.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[THREAT_MODELS_TABLE]) for r in res.rows()]

    async def get_threat_model(self, model_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._threats, model_id, _JSON_FIELDS[THREAT_MODELS_TABLE])

    async def update_threat_model(
        self,
        model_id: int,
        methodology: str | None = None,
        title: str | None = None,
        components: Any = None,
        threats: Any = None,
        summary: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if methodology is not None:
            changes["methodology"] = methodology
        if title is not None:
            changes["title"] = title
        if components is not None:
            changes["components"] = _dumps(components)
        if threats is not None:
            changes["threats"] = _dumps(threats)
        if summary is not None:
            changes["summary"] = summary
        if status is not None:
            changes["status"] = status
        if changes:
            await self._threats.update(model_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._threats, model_id, _JSON_FIELDS[THREAT_MODELS_TABLE])

    async def delete_threat_model(self, model_id: int) -> int:
        res = await self._threats.delete_where({"id": model_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Security Controls (upsert por chave natural (system_name, control_key)) ----- #

    async def _control_by_key(self, system_name: str, control_key: str) -> dict[str, Any] | None:
        res = await self._controls.find(
            where={"system_name": system_name, "control_key": control_key}, limit=1
        )
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[SECURITY_CONTROLS_TABLE]) if rows else None

    async def set_security_control(
        self,
        system_name: str,
        control_key: str,
        name: str | None = None,
        control_type: str | None = None,
        framework_ref: str | None = None,
        details: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._controls.upsert(
            _prune(
                {
                    "system_name": system_name,
                    "control_key": control_key,
                    "name": name,
                    "control_type": control_type,
                    "framework_ref": framework_ref,
                    "details": _dumps(details),
                    "status": status,
                }
            ),
            conflict_columns=["system_name", "control_key"],
            user_id=_SYSTEM_USER,
        )
        row = await self._control_by_key(system_name, control_key)
        return row or {}

    async def list_security_controls(
        self, system_name: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if system_name:
            where["system_name"] = system_name
        if status:
            where["status"] = status
        res = await self._controls.find(
            where=where or None,
            order_by=[
                Sort(column="system_name", direction=SortDirection.ASC),
                Sort(column="control_key", direction=SortDirection.ASC),
            ],
        )
        return [_shape(r, _JSON_FIELDS[SECURITY_CONTROLS_TABLE]) for r in res.rows()]

    async def get_security_control(self, system_name: str, control_key: str) -> dict[str, Any] | None:
        return await self._control_by_key(system_name, control_key)

    async def delete_security_control(self, system_name: str, control_key: str) -> int:
        res = await self._controls.delete_where(
            {"system_name": system_name, "control_key": control_key}, user_id=_SYSTEM_USER
        )
        return res.rowcount

    # -- CVSS Assessments (histórico append-only) ------------------------------ #

    async def save_cvss_assessment(
        self,
        vector: str,
        label: str | None = None,
        base_score: float | None = None,
        severity: str | None = None,
        metrics: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._cvss.insert(
            {
                "label": label,
                "vector": vector,
                "base_score": base_score,
                "severity": severity,
                "metrics": _dumps(metrics),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._cvss, new_id, _JSON_FIELDS[CVSS_ASSESSMENTS_TABLE])
        return row or {}

    async def list_cvss_assessments(
        self, severity: str | None = None, label: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if severity:
            where["severity"] = severity
        if label:
            where["label"] = label
        res = await self._cvss.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[CVSS_ASSESSMENTS_TABLE]) for r in res.rows()]

    async def get_cvss_assessment(self, assessment_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._cvss, assessment_id, _JSON_FIELDS[CVSS_ASSESSMENTS_TABLE])

    async def delete_cvss_assessment(self, assessment_id: int) -> int:
        res = await self._cvss.delete_where({"id": assessment_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Artifacts (histórico append-only) ------------------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: str | None = None,
        meta: Any = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
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
