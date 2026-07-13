"""Store do frontend-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Persistência tenant-scoped (resolvida credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12) e dual-db: o mesmo código serve MySQL (banco-por-
tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Arquitetura "o agente gera, a tool persiste": o store expõe CRUD tipado para as 5
entidades do persona (componentes/páginas/formulários/stories/artefatos). Sem SQL
manual: cada read/write cai no Repository (`find`/`insert`/`update`/`update_where`/
`upsert`/`delete_where`). A ÚNICA chave natural é `route` na página (upsert por
rota); o resto é histórico com chave surrogate `id` e soft-delete canônico.

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
    ComponentRow,
    FormRow,
    FrontendArtifactRow,
    PageRow,
    StoryRow,
)
from .schema import (
    ARTIFACTS_TABLE,
    COMPONENTS_TABLE,
    FORMS_TABLE,
    PAGES_TABLE,
    STORIES_TABLE,
)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O persona não persiste um "ator" de negócio (governança só).
_SYSTEM_USER = 0

# As colunas de tempo (create_on / timestamp_refresh) são injetadas e populadas pela
# fábrica de schema / conventions do ORM — o store nunca as escreve à mão. A ordenação
# dos históricos usa a chave surrogate `id` (monotônica), então tampouco precisa delas.

# Campos JSON serializados em TEXT, por entidade — desserializados na leitura.
_JSON_FIELDS: dict[str, tuple[str, ...]] = {
    COMPONENTS_TABLE: ("props",),
    PAGES_TABLE: ("meta",),
    FORMS_TABLE: ("fields",),
    STORIES_TABLE: ("stories",),
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
    chave natural (``route``) é sempre não-``None``, então nunca é podada.
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


class FrontendStore:
    """Store tenant-scoped: 5 repositórios ligados ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria os
    repositórios canônicos por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._components = session.repository(ComponentRow, table_name=COMPONENTS_TABLE)
        self._pages = session.repository(PageRow, table_name=PAGES_TABLE)
        self._forms = session.repository(FormRow, table_name=FORMS_TABLE)
        self._stories = session.repository(StoryRow, table_name=STORIES_TABLE)
        self._artifacts = session.repository(FrontendArtifactRow, table_name=ARTIFACTS_TABLE)

    # -- helpers de leitura (por id / por chave natural) ----------------------- #

    @staticmethod
    async def _by_id(repo: Any, row_id: int, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        res = await repo.find(where={"id": row_id}, limit=1)
        rows = res.rows()
        return _shape(rows[0], json_fields) if rows else None

    # -- Components ------------------------------------------------------------ #

    async def save_component(
        self,
        name: str,
        variant: str = "functional",
        framework: str | None = None,
        styling: str | None = None,
        props: Any = None,
        code: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._components.insert(
            {
                "name": name,
                "variant": variant,
                "framework": framework,
                "styling": styling,
                "props": _dumps(props),
                "code": code,
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._components, new_id, _JSON_FIELDS[COMPONENTS_TABLE])
        return row or {}

    async def list_components(
        self, name: str | None = None, framework: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if name:
            where["name"] = name
        if framework:
            where["framework"] = framework
        if status:
            where["status"] = status
        res = await self._components.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[COMPONENTS_TABLE]) for r in res.rows()]

    async def get_component(self, component_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._components, component_id, _JSON_FIELDS[COMPONENTS_TABLE])

    async def update_component(
        self,
        component_id: int,
        variant: str | None = None,
        framework: str | None = None,
        styling: str | None = None,
        props: Any = None,
        code: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if variant is not None:
            changes["variant"] = variant
        if framework is not None:
            changes["framework"] = framework
        if styling is not None:
            changes["styling"] = styling
        if props is not None:
            changes["props"] = _dumps(props)
        if code is not None:
            changes["code"] = code
        if status is not None:
            changes["status"] = status
        if changes:
            await self._components.update(component_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._components, component_id, _JSON_FIELDS[COMPONENTS_TABLE])

    async def delete_component(self, component_id: int) -> int:
        res = await self._components.delete_where({"id": component_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Pages (upsert por chave natural `route`) ------------------------------ #

    async def _page_by_route(self, route: str) -> dict[str, Any] | None:
        res = await self._pages.find(where={"route": route}, limit=1)
        rows = res.rows()
        return _shape(rows[0], _JSON_FIELDS[PAGES_TABLE]) if rows else None

    async def set_page(
        self,
        route: str,
        title: str | None = None,
        framework: str | None = None,
        page_type: str | None = None,
        code: str | None = None,
        meta: Any = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        await self._pages.upsert(
            _prune(
                {
                    "route": route,
                    "title": title,
                    "framework": framework,
                    "page_type": page_type,
                    "code": code,
                    "meta": _dumps(meta),
                    "status": status,
                }
            ),
            conflict_columns=["route"],
            user_id=_SYSTEM_USER,
        )
        row = await self._page_by_route(route)
        return row or {}

    async def list_pages(
        self, framework: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if framework:
            where["framework"] = framework
        if status:
            where["status"] = status
        res = await self._pages.find(
            where=where or None,
            order_by=[Sort(column="route", direction=SortDirection.ASC)],
        )
        return [_shape(r, _JSON_FIELDS[PAGES_TABLE]) for r in res.rows()]

    async def get_page(self, route: str) -> dict[str, Any] | None:
        return await self._page_by_route(route)

    async def delete_page(self, route: str) -> int:
        res = await self._pages.delete_where({"route": route}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Forms ----------------------------------------------------------------- #

    async def save_form(
        self,
        name: str,
        library: str | None = None,
        validation: str | None = None,
        fields: Any = None,
        code: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._forms.insert(
            {
                "name": name,
                "library": library,
                "validation": validation,
                "fields": _dumps(fields),
                "code": code,
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._forms, new_id, _JSON_FIELDS[FORMS_TABLE])
        return row or {}

    async def list_forms(self, name: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if name:
            where["name"] = name
        if status:
            where["status"] = status
        res = await self._forms.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[FORMS_TABLE]) for r in res.rows()]

    async def get_form(self, form_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._forms, form_id, _JSON_FIELDS[FORMS_TABLE])

    async def update_form(
        self,
        form_id: int,
        library: str | None = None,
        validation: str | None = None,
        fields: Any = None,
        code: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if library is not None:
            changes["library"] = library
        if validation is not None:
            changes["validation"] = validation
        if fields is not None:
            changes["fields"] = _dumps(fields)
        if code is not None:
            changes["code"] = code
        if status is not None:
            changes["status"] = status
        if changes:
            await self._forms.update(form_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._forms, form_id, _JSON_FIELDS[FORMS_TABLE])

    async def delete_form(self, form_id: int) -> int:
        res = await self._forms.delete_where({"id": form_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Stories --------------------------------------------------------------- #

    async def save_story(
        self,
        component: str,
        title: str | None = None,
        framework: str | None = None,
        stories: Any = None,
        code: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        res = await self._stories.insert(
            {
                "component": component,
                "title": title,
                "framework": framework,
                "stories": _dumps(stories),
                "code": code,
                "status": status,
            },
            user_id=_SYSTEM_USER,
        )
        new_id = int(res.returned_id) if res.returned_id is not None else 0
        row = await self._by_id(self._stories, new_id, _JSON_FIELDS[STORIES_TABLE])
        return row or {}

    async def list_stories(
        self, component: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if component:
            where["component"] = component
        if status:
            where["status"] = status
        res = await self._stories.find(
            where=where or None,
            order_by=[Sort(column="id", direction=SortDirection.DESC)],
        )
        return [_shape(r, _JSON_FIELDS[STORIES_TABLE]) for r in res.rows()]

    async def get_story(self, story_id: int) -> dict[str, Any] | None:
        return await self._by_id(self._stories, story_id, _JSON_FIELDS[STORIES_TABLE])

    async def update_story(
        self,
        story_id: int,
        title: str | None = None,
        framework: str | None = None,
        stories: Any = None,
        code: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {}
        if title is not None:
            changes["title"] = title
        if framework is not None:
            changes["framework"] = framework
        if stories is not None:
            changes["stories"] = _dumps(stories)
        if code is not None:
            changes["code"] = code
        if status is not None:
            changes["status"] = status
        if changes:
            await self._stories.update(story_id, changes, user_id=_SYSTEM_USER)
        return await self._by_id(self._stories, story_id, _JSON_FIELDS[STORIES_TABLE])

    async def delete_story(self, story_id: int) -> int:
        res = await self._stories.delete_where({"id": story_id}, user_id=_SYSTEM_USER)
        return res.rowcount

    # -- Artifacts (histórico append-only) ------------------------------------- #

    async def save_artifact(
        self,
        kind: str,
        target: str,
        content: str,
        framework: str | None = None,
        meta: Any = None,
    ) -> dict[str, Any]:
        res = await self._artifacts.insert(
            {
                "kind": kind,
                "target": target,
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
