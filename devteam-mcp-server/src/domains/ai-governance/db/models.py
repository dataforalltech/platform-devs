"""Entidades canônicas dos stores do ai-governance-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * A coluna de **chave natural** (``suggestion_id``) carrega um ``max_length``
    explícito para virar ``VARCHAR(n)`` (indexável em UNIQUE) em vez de ``TEXT`` —
    MySQL não indexa ``TEXT`` sem prefixo de tamanho.
  * O MySQL emite identificadores **sem aspas** (parity legado + regex de RETURNING
    do pool), então nenhuma coluna pode ter nome de palavra reservada. Por isso o
    campo ``references`` do domínio vira a coluna ``reference_links`` (``REFERENCES``
    é reservado no MySQL); o store faz o mapeamento de volta para ``references``.
  * As listas/estruturas aninhadas (related_files/references/status_history/
    violations/…) são serializadas como JSON em colunas ``TEXT`` (sem ``max_length``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SuggestionRow(BaseModel):
    """Uma sugestão cross-repo (chave natural única: ``suggestion_id``).

    A ``suggestion_id`` é o handle público sortable ``YYYYMMDDTHHMMSSffffff-XXXXXXXX``
    (id-arquivo do store antigo); vira ``VARCHAR(64)`` UNIQUE + ``id`` surrogate.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    suggestion_id: str = Field(max_length=64)  # chave natural única -> VARCHAR(64)
    created_at: str | None = None
    source_agent: str | None = Field(default=None, max_length=255)
    source_repo: str | None = Field(default=None, max_length=255)
    target_repo: str | None = Field(default=None, max_length=255)
    target_repo_canonical: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=32)
    severity: str | None = Field(default=None, max_length=32)
    title: str | None = None
    description: str | None = None
    related_files: str | None = None  # JSON serializado (TEXT)
    reference_links: str | None = None  # JSON serializado (TEXT); domínio: `references`
    status: str | None = Field(default=None, max_length=32)
    status_history: str | None = None  # JSON serializado (TEXT)


class DecisionAuditRow(BaseModel):
    """Uma entrada da trilha de auditoria de ``validate_agent_decision``.

    Append-only, chave surrogate ``id``. A ordem cronológica reversa é recuperada
    por ``id DESC`` (autoincrement = ordem de inserção).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    ts: str | None = None
    repo: str | None = Field(default=None, max_length=255)
    task_description: str | None = None
    approved: int | None = None  # 0/1 (bool não é indexável de forma portável)
    risk_level: str | None = Field(default=None, max_length=32)
    violations_count: int | None = None
    violations: str | None = None  # JSON serializado (TEXT)
    required_actions_count: int | None = None
    required_actions: str | None = None  # JSON serializado (TEXT)
    affected_layers: str | None = None  # JSON serializado (TEXT)
    affected_files_count: int | None = None
    flags: str | None = None  # JSON serializado (TEXT)


__all__ = ["SuggestionRow", "DecisionAuditRow"]
