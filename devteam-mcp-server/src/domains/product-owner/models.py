"""Entidades canônicas do store do product-owner-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool persiste"): o persona não
cospe mais template fixo — o agente chamador fornece o artefato (user story, escopo de
MVP, visão de produto, persona, item de backlog, jornada/riscos/handoff/...) e a tool
o **persiste** no banco do tenant. Cada entidade é um histórico consultável (list/get)
e mutável (update/soft-delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``feature``/``product``/``name``/``role``/...)
    carregam um ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável/curto)
    em vez de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho. ``product``
    é chave natural única em MVPScope e ProductVision (um por produto → UNIQUE +
    upsert).
  * Dados estruturados (acceptance_criteria/content/goals/pains/meta) são **JSON
    serializado em ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON nativa).
    Texto longo livre (``benefit``/``story``/``goal``/``vision``) também é ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserStoryRow(BaseModel):
    """Uma user story persistida (chave surrogate ``id``, histórico por feature)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    feature: str = Field(max_length=200)  # feature/épico alvo -> VARCHAR(200)
    role: str = Field(max_length=120)  # papel/persona -> VARCHAR(120)
    goal: str | None = Field(default=None, max_length=300)  # objetivo/ação -> VARCHAR(300)
    benefit: str | None = None  # benefício/valor (TEXT, texto livre)
    story: str | None = None  # a sentença "As a ... I want ... so that ..." (TEXT)
    acceptance_criteria: str | None = None  # JSON serializado (TEXT): lista de critérios
    priority: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=20)


class MVPScopeRow(BaseModel):
    """Escopo de MVP de um produto (chave natural única: ``product`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    product: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    goal: str | None = None  # objetivo do MVP (TEXT, texto livre)
    content: str | None = None  # JSON serializado (TEXT): core/should/could/out_of_scope
    status: str | None = Field(default=None, max_length=20)


class ProductVisionRow(BaseModel):
    """Visão de produto (chave natural única: ``product`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    product: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    target_audience: str | None = Field(default=None, max_length=300)
    vision: str | None = None  # a sentença de visão (TEXT, texto livre)
    content: str | None = None  # JSON serializado (TEXT): mission/goals/success_criteria/differentiator
    status: str | None = Field(default=None, max_length=20)


class UserPersonaRow(BaseModel):
    """Uma persona de usuário persistida (chave surrogate ``id``, histórico)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = Field(max_length=200)  # nome da persona -> VARCHAR(200)
    segment: str | None = Field(default=None, max_length=200)
    demographics: str | None = None  # JSON serializado (TEXT): mapa demográfico
    goals: str | None = None  # JSON serializado (TEXT): lista de objetivos
    pains: str | None = None  # JSON serializado (TEXT): lista de dores
    behaviors: str | None = None  # JSON serializado (TEXT): lista de comportamentos


class BacklogItemRow(BaseModel):
    """Um item de backlog priorizado (chave surrogate ``id``, histórico).

    Os campos RICE (``reach``/``impact``/``confidence``/``effort``) são escalares
    (colunas numéricas queryáveis); ``score`` é o resultado determinístico de
    ``calculate_rice_score`` (dobrado no ``save_backlog_item`` quando ausente)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = Field(max_length=300)  # nome/título do item -> VARCHAR(300)
    framework: str | None = Field(default=None, max_length=20)  # RICE/ICE/MoSCoW
    reach: float | None = None
    impact: float | None = None
    confidence: float | None = None
    effort: float | None = None
    score: float | None = None  # score determinístico (RICE) — dobrado no save
    status: str | None = Field(default=None, max_length=20)


class PoArtifactRow(BaseModel):
    """Um artefato de PO gerado pelo agente e persistido (histórico append-only, ``id``).

    ``content`` guarda o artefato estruturado que o agente gerou (jornada, riscos,
    handoff, discovery, gtm, release, feature_spec, métricas, análise de problema...) —
    JSON serializado. ``meta`` é JSON serializado."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # journey|risks|handoff_architecture|handoff_design|handoff_engineering|discovery|
    # gtm|release|feature_spec|metrics|problem
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # feature/product/persona alvo
    content: str | None = None  # JSON serializado (TEXT): o artefato gerado
    meta: str | None = None  # JSON serializado (TEXT)


__all__ = [
    "UserStoryRow",
    "MVPScopeRow",
    "ProductVisionRow",
    "UserPersonaRow",
    "BacklogItemRow",
    "PoArtifactRow",
]
