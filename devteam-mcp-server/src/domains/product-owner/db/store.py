"""Store do product-owner-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 6
entidades do persona (user stories/escopos de MVP/visões/personas/itens de backlog/
artefatos). Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/
`update`/`update_where`/`upsert`/`delete_where`). As chaves naturais são `product`
(upsert em MVPScope e ProductVision, um por produto); o resto é histórico com chave
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
    BacklogItemRow,
    MVPScopeRow,
    PoArtifactRow,
    ProductVisionRow,
    UserPersonaRow,
    UserStoryRow,
)
from .schema import (
    ARTIFACTS_TABLE,
    BACKLOG_ITEMS_TABLE,
    MVP_SCOPES_TABLE,
    PRODUCT_VISIONS_TABLE,
    USER_PERSONAS_TABLE,
    USER_STORIES_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    USER_STORIES_TABLE: ("acceptance_criteria",),
    MVP_SCOPES_TABLE: ("content",),
    PRODUCT_VISIONS_TABLE: ("content",),
    USER_PERSONAS_TABLE: ("demographics", "goals", "pains", "behaviors"),
    BACKLOG_ITEMS_TABLE: (),
    ARTIFACTS_TABLE: ("content", "meta"),
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
    chave natural (``product``) é sempre não-``None``, então nunca é podada.
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


class ProductOwnerStore:
    """Store tenant-scoped: 6 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._stories = session.repository(UserStoryRow, table_name=USER_STORIES_TABLE)
        self._mvps = session.repository(MVPScopeRow, table_name=MVP_SCOPES_TABLE)
        self._visions = session.repository(ProductVisionRow, table_name=PRODUCT_VISIONS_TABLE)
        self._personas = session.repository(UserPersonaRow, table_name=USER_PERSONAS_TABLE)
        self._backlog = session.repository(BacklogItemRow, table_name=BACKLOG_ITEMS_TABLE)
        self._artifacts = session.repository(PoArtifactRow, table_name=ARTIFACTS_TABLE)

    # -- helpers de leitura (por id / por chave natural) ----------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- User Stories ---------------------------------------------------------- #

    async def save_user_story(
        self,
        feature: str,
        role: str,
        goal: str | None = None,
        benefit: str | None = None,
        story: str | None = None,
        acceptance_criteria: Any = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._stories.insert(
            {
                "feature": feature,
                "role": role,
                "goal": goal,
                "benefit": benefit,
                "story": story,
                "acceptance_criteria": _dumps(acceptance_criteria),
                "priority": priority,
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._stories, new_id, _JSON_FIELDS[USER_STORIES_TABLE])
        return row or {}

    async def list_user_stories(
        self, feature: str | None = None, role: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if feature:
            where["feature"] = feature
        if role:
            where["role"] = role
        if status:
            where["status"] = status
        res = await self._stories.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[USER_STORIES_TABLE]) for r in res.rows()]

    async def get_user_story(self, story_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._stories, story_id, _JSON_FIELDS[USER_STORIES_TABLE])

    async def update_user_story(
        self,
        story_id: int,
        role: str | None = None,
        goal: str | None = None,
        benefit: str | None = None,
        story: str | None = None,
        acceptance_criteria: Any = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if role is not None:
            changes["role"] = role
        if goal is not None:
            changes["goal"] = goal
        if benefit is not None:
            changes["benefit"] = benefit
        if story is not None:
            changes["story"] = story
        if acceptance_criteria is not None:
            changes["acceptance_criteria"] = _dumps(acceptance_criteria)
        if priority is not None:
            changes["priority"] = priority
        if status is not None:
            changes["status"] = status
        if changes:
            await self._stories.update(story_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._stories, story_id, _JSON_FIELDS[USER_STORIES_TABLE])

    async def delete_user_story(self, story_id: int) -> int:
        res = await self._stories.delete_where({"id": story_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- MVP Scopes (upsert por chave natural `product`) ----------------------- #

    async def _mvp_by_product(self, product: str) -> dict[str, Any] | None:
        res = await self._mvps.find(where={"product": product}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[MVP_SCOPES_TABLE]) if rows else None

    async def set_mvp_scope(
        self, product: str, content: Any, goal: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        await self._mvps.upsert(
            _prune(
                {
                    "product": product,
                    "goal": goal,
                    "content": _dumps(content),
                    "status": status,
                }
            ),
            conflict_columns=["product"],
            user_id=_SYSTEM_USER,
        )
        row = await self._mvp_by_product(product)
        return row or {}

    async def list_mvp_scopes(self, status: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if status:
            where["status"] = status
        res = await self._mvps.find(
            where=where or None,
            order_by=[Sort(column="product", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[MVP_SCOPES_TABLE]) for r in res.rows()]

    async def get_mvp_scope(self, product: str) -> dict[str, Any] | None:
        return await self._mvp_by_product(product)

    async def delete_mvp_scope(self, product: str) -> int:
        res = await self._mvps.delete_where({"product": product}, user_id=_SYSTEM_USER)
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
        target_audience: str | None = None,
        content: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._visions.upsert(
            _prune(
                {
                    "product": product,
                    "target_audience": target_audience,
                    "vision": vision,
                    "content": _dumps(content),
                    "status": status,
                }
            ),
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

    # -- User Personas (histórico) --------------------------------------------- #

    async def save_user_persona(
        self,
        name: str,
        segment: str | None = None,
        demographics: Any = None,
        goals: Any = None,
        pains: Any = None,
        behaviors: Any = None,
    ) -> dict[str, Any]:
        res = await self._personas.insert(
            {
                "name": name,
                "segment": segment,
                "demographics": _dumps(demographics),
                "goals": _dumps(goals),
                "pains": _dumps(pains),
                "behaviors": _dumps(behaviors),
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._personas, new_id, _JSON_FIELDS[USER_PERSONAS_TABLE])
        return row or {}

    async def list_user_personas(
        self, segment: str | None = None, name: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if segment:
            where["segment"] = segment
        if name:
            where["name"] = name
        res = await self._personas.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[USER_PERSONAS_TABLE]) for r in res.rows()]

    async def get_user_persona(self, persona_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._personas, persona_id, _JSON_FIELDS[USER_PERSONAS_TABLE])

    async def update_user_persona(
        self,
        persona_id: int,
        segment: str | None = None,
        demographics: Any = None,
        goals: Any = None,
        pains: Any = None,
        behaviors: Any = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if segment is not None:
            changes["segment"] = segment
        if demographics is not None:
            changes["demographics"] = _dumps(demographics)
        if goals is not None:
            changes["goals"] = _dumps(goals)
        if pains is not None:
            changes["pains"] = _dumps(pains)
        if behaviors is not None:
            changes["behaviors"] = _dumps(behaviors)
        if changes:
            await self._personas.update(persona_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._personas, persona_id, _JSON_FIELDS[USER_PERSONAS_TABLE])

    async def delete_user_persona(self, persona_id: int) -> int:
        res = await self._personas.delete_where({"id": persona_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Backlog Items (histórico; score determinístico RICE) ------------------ #

    async def save_backlog_item(
        self,
        name: str,
        framework: str | None = None,
        reach: float | None = None,
        impact: float | None = None,
        confidence: float | None = None,
        effort: float | None = None,
        score: float | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._backlog.insert(
            {
                "name": name,
                "framework": framework,
                "reach": reach,
                "impact": impact,
                "confidence": confidence,
                "effort": effort,
                "score": score,
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._backlog, new_id, _JSON_FIELDS[BACKLOG_ITEMS_TABLE])
        return row or {}

    async def list_backlog_items(
        self, framework: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if framework:
            where["framework"] = framework
        if status:
            where["status"] = status
        res = await self._backlog.find(
            where=where or None,
            order_by=[
                Sort(column="score", direction=SortDirection.DESC),
                Sort(column="id", direction=SortDirection.DESC),
            ],
        )
        return [_shape(r, _JSON_FIELDS[BACKLOG_ITEMS_TABLE]) for r in res.rows()]

    async def get_backlog_item(self, item_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._backlog, item_id, _JSON_FIELDS[BACKLOG_ITEMS_TABLE])

    async def update_backlog_item(
        self,
        item_id: int,
        framework: str | None = None,
        reach: float | None = None,
        impact: float | None = None,
        confidence: float | None = None,
        effort: float | None = None,
        score: float | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if framework is not None:
            changes["framework"] = framework
        if reach is not None:
            changes["reach"] = reach
        if impact is not None:
            changes["impact"] = impact
        if confidence is not None:
            changes["confidence"] = confidence
        if effort is not None:
            changes["effort"] = effort
        if score is not None:
            changes["score"] = score
        if status is not None:
            changes["status"] = status
        if changes:
            await self._backlog.update(item_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._backlog, item_id, _JSON_FIELDS[BACKLOG_ITEMS_TABLE])

    async def delete_backlog_item(self, item_id: int) -> int:
        res = await self._backlog.delete_where({"id": item_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Artifacts (histórico append-only) ------------------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: Any = None,
        meta: Any = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
                "content": _dumps(content),
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
