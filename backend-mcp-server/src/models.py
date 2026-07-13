"""Entidades canônicas do store do backend-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool persiste"): o persona não
gera mais template fixo — o agente chamador fornece o artefato de código backend
(contrato de API, schema de banco, política de auth, router/migration/service, review)
e a tool o **persiste** no banco do tenant. Cada entidade é um histórico consultável
(list/get) e mutável (update/soft-delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``endpoint``/``method``/``entity``/``resource``/...)
    carregam um ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável/curto)
    em vez de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho. Há DUAS
    chaves naturais únicas: ``(endpoint, method)`` no contrato de API (um contrato por
    endpoint+verbo → UNIQUE composta + upsert) e ``resource`` na política de auth (uma
    política por recurso → UNIQUE + upsert).
  * Dados estruturados (schemas/attributes/roles/meta/findings) são **JSON serializado
    em ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON nativa). Texto/código
    longo livre (``description``/``content``/``summary``) também é ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class APIContractRow(BaseModel):
    """Um contrato de API persistido (chave natural única composta: ``endpoint``+``method``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    endpoint: str = Field(max_length=255)  # path do endpoint -> VARCHAR(255)
    method: str = Field(max_length=10)  # GET/POST/... -> VARCHAR(10)
    description: str | None = None  # texto livre (TEXT)
    request_schema: str | None = None  # JSON serializado (TEXT)
    response_schema: str | None = None  # JSON serializado (TEXT)
    status_codes: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class DatabaseSchemaRow(BaseModel):
    """Um schema de banco persistido (chave surrogate ``id``; histórico por entidade)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    entity: str = Field(max_length=200)  # entidade/tabela -> VARCHAR(200)
    # `database` é palavra reservada do MySQL 8 e o ORM emite identificadores
    # UNQUOTED -> nome físico da coluna vira `database_name` (o dialeto não pode
    # quotar reserved words sem quebrar a emulação de RETURNING do pool MySQL).
    database_name: str = Field(max_length=40)  # postgres/mysql/... -> VARCHAR(40)
    attributes: str | None = None  # JSON serializado (TEXT)
    relationships: str | None = None  # JSON serializado (TEXT)
    indexes: str | None = None  # JSON serializado (TEXT)
    constraints: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class AuthPolicyRow(BaseModel):
    """Uma política de auth por recurso (chave natural única: ``resource`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    resource: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    auth_type: str = Field(max_length=40)  # jwt/oauth/... -> VARCHAR(40)
    roles: str | None = None  # JSON serializado (TEXT)
    data_sensitivity: str | None = Field(default=None, max_length=40)
    rules: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class BackendArtifactRow(BaseModel):
    """Um artefato de código backend gerado pelo agente e persistido (histórico, ``id``).

    ``content`` guarda o código que o agente gerou (router FastAPI, controller NestJS,
    migration, service/repository layer, spec OpenAPI, fluxo de integração) — texto
    livre, não JSON. ``meta`` é JSON serializado.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # router|migration|service_layer|repository|openapi_spec|nestjs_controller|integration
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # nome/módulo/serviço alvo
    language: str | None = Field(default=None, max_length=40)
    framework: str | None = Field(default=None, max_length=40)
    content: str | None = None  # o código gerado (TEXT, texto livre)
    meta: str | None = None  # JSON serializado (TEXT)


class CodeReviewRow(BaseModel):
    """Uma revisão de código backend persistida (chave surrogate ``id``; histórico)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    target: str = Field(max_length=300)  # arquivo/módulo/serviço revisado
    language: str = Field(max_length=40)  # python/typescript/... -> VARCHAR(40)
    focus: str | None = None  # JSON serializado (TEXT): focos da revisão
    findings: str | None = None  # JSON serializado (TEXT): achados
    security_score: float | None = None  # score determinístico (opcional)
    performance_score: float | None = None  # score determinístico (opcional)
    summary: str | None = None  # texto livre (TEXT)
    status: str | None = Field(default=None, max_length=20)


__all__ = [
    "APIContractRow",
    "DatabaseSchemaRow",
    "AuthPolicyRow",
    "BackendArtifactRow",
    "CodeReviewRow",
]
