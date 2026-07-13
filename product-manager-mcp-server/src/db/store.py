"""Store do product-manager-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 5
entidades do persona (feature specs/GTM briefs/release plans/product visions/
artefatos). Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/
`update`/`update_where`/`upsert`/`delete_where`). A ÚNICA chave natural é `product`
na visão (upsert por produto); o resto é histórico com chave surrogate `id` e
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
    FeatureSpecRow,
    GtmBriefRow,
    PmArtifactRow,
    ProductVisionRow,
    ReleasePlanRow,
)
from .schema import (
    ARTIFACTS_TABLE,
    FEATURE_SPECS_TABLE,
    GTM_BRIEFS_TABLE,
    PRODUCT_VISIONS_TABLE,
    RELEASE_PLANS_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    FEATURE_SPECS_TABLE: ("content",),
    GTM_BRIEFS_TABLE: ("content",),
    RELEASE_PLANS_TABLE: ("content",),
    PRODUCT_VISIONS_TABLE: ("goals",),
    ARTIFACTS_TABLE: ("meta",),
}


def _dumps(value: Any) -> str | None:
    """Serializa dict/list em JSON (TEXT). ``None`` permanece ``None`` (coluna NULL)."""
    return None if value is None else json.dumps(value, ensure_ascii=False)


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


class ProductManagerStore:
    """Store tenant-scoped: 5 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._specs = session.repository(FeatureSpecRow, table_name=FEATURE_SPECS_TABLE)
        self._briefs = session.repository(GtmBriefRow, table_name=GTM_BRIEFS_TABLE)
        self._plans = session.repository(ReleasePlanRow, table_name=RELEASE_PLANS_TABLE)
        self._visions = session.repository(ProductVisionRow, table_name=PRODUCT_VISIONS_TABLE)
        self._artifacts = session.repository(PmArtifactRow, table_name=ARTIFACTS_TABLE)

    # -- helpers de leitura (por id / por chave natural) ----------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- Feature Specs --------------------------------------------------------- #

    async def save_feature_spec(
        self,
        feature: str,
        content: Any,
        objective: str | None = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._specs.insert(
            {
                "feature": feature,
                "objective": objective,
                "priority": priority,
                "content": _dumps(content),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._specs, new_id, _JSON_FIELDS[FEATURE_SPECS_TABLE])
        return row or {}

    async def list_feature_specs(
        self, feature: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if feature:
            where["feature"] = feature
        if status:
            where["status"] = status
        res = await self._specs.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[FEATURE_SPECS_TABLE]) for r in res.rows()]

    async def get_feature_spec(self, spec_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._specs, spec_id, _JSON_FIELDS[FEATURE_SPECS_TABLE])

    async def update_feature_spec(
        self,
        spec_id: int,
        objective: str | None = None,
        priority: str | None = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if objective is not None:
            changes["objective"] = objective
        if priority is not None:
            changes["priority"] = priority
        if content is not None:
            changes["content"] = _dumps(content)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._specs.update(spec_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._specs, spec_id, _JSON_FIELDS[FEATURE_SPECS_TABLE])

    async def delete_feature_spec(self, spec_id: int) -> int:
        res = await self._specs.delete_where({"id": spec_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- GTM Briefs ------------------------------------------------------------ #

    async def save_gtm_brief(
        self,
        product: str,
        content: Any,
        launch_timing: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._briefs.insert(
            {
                "product": product,
                "launch_timing": launch_timing,
                "content": _dumps(content),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._briefs, new_id, _JSON_FIELDS[GTM_BRIEFS_TABLE])
        return row or {}

    async def list_gtm_briefs(
        self, product: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if product:
            where["product"] = product
        if status:
            where["status"] = status
        res = await self._briefs.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[GTM_BRIEFS_TABLE]) for r in res.rows()]

    async def get_gtm_brief(self, brief_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._briefs, brief_id, _JSON_FIELDS[GTM_BRIEFS_TABLE])

    async def update_gtm_brief(
        self,
        brief_id: int,
        launch_timing: str | None = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if launch_timing is not None:
            changes["launch_timing"] = launch_timing
        if content is not None:
            changes["content"] = _dumps(content)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._briefs.update(brief_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._briefs, brief_id, _JSON_FIELDS[GTM_BRIEFS_TABLE])

    async def delete_gtm_brief(self, brief_id: int) -> int:
        res = await self._briefs.delete_where({"id": brief_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Release Plans --------------------------------------------------------- #

    async def save_release_plan(
        self,
        product: str,
        content: Any,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._plans.insert(
            {
                "product": product,
                "content": _dumps(content),
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._plans, new_id, _JSON_FIELDS[RELEASE_PLANS_TABLE])
        return row or {}

    async def list_release_plans(
        self, product: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if product:
            where["product"] = product
        if status:
            where["status"] = status
        res = await self._plans.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[RELEASE_PLANS_TABLE]) for r in res.rows()]

    async def get_release_plan(self, plan_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._plans, plan_id, _JSON_FIELDS[RELEASE_PLANS_TABLE])

    async def update_release_plan(
        self,
        plan_id: int,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if content is not None:
            changes["content"] = _dumps(content)
        if status is not None:
            changes["status"] = status
        if changes:
            await self._plans.update(plan_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._plans, plan_id, _JSON_FIELDS[RELEASE_PLANS_TABLE])

    async def delete_release_plan(self, plan_id: int) -> int:
        res = await self._plans.delete_where({"id": plan_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Product Visions (upsert por chave natural `product`) ------------------ #

    async def _vision_by_product(self, product: str) -> dict[str, Any] | None:
        res = await self._visions.find(where={"product": product}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[PRODUCT_VISIONS_TABLE]) if rows else None

    async def set_product_vision(
        self,
        product: str,
        vision: str | None = None,
        mission: str | None = None,
        goals: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._visions.upsert(
            {
                "product": product,
                "vision": vision,
                "mission": mission,
                "goals": _dumps(goals),
                "status": status,
            },
            conflict_columns=["product"],
            user_id=_SYSTEM_USER,
        )
        row = await self._vision_by_product(product)
        return row or {}

    async def list_product_visions(self, status: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if status:
            where["status"] = status
        res = await self._visions.find(
            where=where or None,
            order_by=[Sort(column="product", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[PRODUCT_VISIONS_TABLE]) for r in res.rows()]

    async def get_product_vision(self, product: str) -> dict[str, Any] | None:
        return await self._vision_by_product(product)

    async def delete_product_vision(self, product: str) -> int:
        res = await self._visions.delete_where({"product": product}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Artifacts (histórico append-only) ------------------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: str,
        fmt: str | None = None,
        meta: Any = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
                "fmt": fmt,
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
