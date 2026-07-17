"""Entidades canônicas do store do product-manager-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool persiste"): o persona não
gera mais template fixo — o agente chamador fornece o artefato de produto (feature
spec, GTM brief, release plan, product vision) e a tool o **persiste** no banco do
tenant. Cada entidade é um histórico consultável (list/get) e mutável (update/soft-
delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``feature``/``product``/``kind``/...) carregam um
    ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável/curto) em vez de
    ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho. ``product`` na visão
    é a única **chave natural única** (uma visão por produto → UNIQUE + upsert).
  * Dados estruturados (user_stories/acceptance_criteria/goals/meta) são **JSON
    serializado em ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON
    nativa). Texto longo livre (``objective``/``vision``/``mission``/``content``)
    também é ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureSpecRow(BaseModel):
    """Uma feature spec persistida (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    feature: str = Field(max_length=200)  # funcionalidade alvo -> VARCHAR(200)
    objective: str | None = None  # texto livre (TEXT)
    priority: str | None = Field(default=None, max_length=20)  # high/medium/low -> VARCHAR(20)
    content: str | None = None  # JSON serializado (TEXT): user_stories/acceptance_criteria/...
    status: str | None = Field(default=None, max_length=20)


class GtmBriefRow(BaseModel):
    """Um go-to-market brief persistido (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    product: str = Field(max_length=200)  # produto/lançamento alvo -> VARCHAR(200)
    launch_timing: str | None = Field(default=None, max_length=40)  # ex.: "Q2 2026" -> VARCHAR(40)
    content: str | None = None  # JSON serializado (TEXT): target_segment/key_messages/channels/...
    status: str | None = Field(default=None, max_length=20)


class ReleasePlanRow(BaseModel):
    """Um plano de release persistido (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    product: str = Field(max_length=200)  # produto alvo -> VARCHAR(200)
    content: str | None = None  # JSON serializado (TEXT): phases/timeline/features_per_phase
    status: str | None = Field(default=None, max_length=20)


class ProductVisionRow(BaseModel):
    """Uma visão de produto (chave natural única: ``product`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    product: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    vision: str | None = None  # texto livre (TEXT)
    mission: str | None = None  # texto livre (TEXT)
    goals: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class PmArtifactRow(BaseModel):
    """Um artefato de produto gerado pelo agente e persistido (histórico append-only, ``id``).

    ``content`` guarda o texto/documento que o agente gerou (roadmap, PRD, OKR,
    persona, user story, etc.) — texto livre, não JSON. ``meta`` é JSON serializado.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # product_vision|feature_spec|gtm_brief|release_plan|roadmap|prd|okr|persona|user_story|discovery|analysis
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # produto/feature/segmento
    fmt: str | None = Field(default=None, max_length=40)  # markdown/json/... (opcional)
    content: str | None = None  # o texto/documento gerado (TEXT, texto livre)
    meta: str | None = None  # JSON serializado (TEXT)


__all__ = [
    "FeatureSpecRow",
    "GtmBriefRow",
    "ReleasePlanRow",
    "ProductVisionRow",
    "PmArtifactRow",
]
