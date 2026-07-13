"""Entidades canônicas do store do frontend-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool persiste"): o persona não
gera mais template fixo — o agente chamador fornece o artefato de UI (componente
React, página Next.js, formulário, story) e a tool o **persiste** no banco do
tenant. Cada entidade é um histórico consultável (list/get) e mutável
(update/soft-delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``name``/``route``/``component``/...) carregam um
    ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável/curto) em vez de
    ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho. ``route`` é a única
    **chave natural única** (uma página por rota → UNIQUE + upsert).
  * Dados estruturados (props/fields/stories/meta) são **JSON serializado em
    ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON nativa). O código-
    fonte gerado (``code``/``content``) também é ``TEXT`` (texto livre).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ComponentRow(BaseModel):
    """Um componente React persistido (chave surrogate ``id``, histórico)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = Field(max_length=200)  # nome do componente -> VARCHAR(200)
    variant: str = Field(max_length=40)  # functional/class/... -> VARCHAR(40)
    framework: str | None = Field(default=None, max_length=40)  # react/preact/...
    styling: str | None = Field(default=None, max_length=40)  # tailwind/css-modules/...
    props: str | None = None  # JSON serializado (TEXT): props/typescript interface
    code: str | None = None  # código-fonte gerado pelo agente (TEXT, texto livre)
    status: str | None = Field(default=None, max_length=20)


class PageRow(BaseModel):
    """Uma página Next.js (chave natural única: ``route`` → upsert).

    Uma página por rota — re-gerar a página da mesma rota sobrescreve (upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    route: str = Field(max_length=300)  # chave natural única -> VARCHAR(300)
    title: str | None = Field(default=None, max_length=300)
    framework: str | None = Field(default=None, max_length=40)  # nextjs/remix/...
    page_type: str | None = Field(default=None, max_length=40)  # app-route/pages-route
    code: str | None = None  # código-fonte gerado (TEXT, texto livre)
    meta: str | None = None  # JSON serializado (TEXT): layout/metadata/loaders
    status: str | None = Field(default=None, max_length=20)


class FormRow(BaseModel):
    """Um formulário persistido (chave surrogate ``id``, histórico)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = Field(max_length=200)  # nome do formulário -> VARCHAR(200)
    library: str | None = Field(default=None, max_length=40)  # react-hook-form/formik
    validation: str | None = Field(default=None, max_length=40)  # zod/yup/...
    fields: str | None = None  # JSON serializado (TEXT): campos + regras
    code: str | None = None  # código-fonte gerado (TEXT, texto livre)
    status: str | None = Field(default=None, max_length=20)


class StoryRow(BaseModel):
    """Uma story de Storybook persistida (chave surrogate ``id``, histórico)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    component: str = Field(max_length=200)  # componente-alvo -> VARCHAR(200)
    title: str | None = Field(default=None, max_length=300)
    framework: str | None = Field(default=None, max_length=40)  # storybook/csf
    stories: str | None = None  # JSON serializado (TEXT): lista de stories
    code: str | None = None  # código-fonte gerado (TEXT, texto livre)
    status: str | None = Field(default=None, max_length=20)


class FrontendArtifactRow(BaseModel):
    """Um artefato de UI gerado pelo agente e persistido (histórico append-only, ``id``).

    Guarda-chuva genérico: ``content`` guarda o código/scaffold que o agente gerou
    (hook, layout, context, style, util, ou os próprios react_component/nextjs_page/
    form/storybook_story) — texto livre, não JSON. ``meta`` é JSON serializado.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # react_component|nextjs_page|form|storybook_story|hook|layout|context|style|util|api_client
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # componente/rota/módulo alvo
    framework: str | None = Field(default=None, max_length=40)
    content: str | None = None  # o código/scaffold gerado (TEXT, texto livre)
    meta: str | None = None  # JSON serializado (TEXT)


__all__ = [
    "ComponentRow",
    "PageRow",
    "FormRow",
    "StoryRow",
    "FrontendArtifactRow",
]
