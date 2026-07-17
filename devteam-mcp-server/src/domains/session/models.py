"""Entidades canônicas do store do session-mcp (Pydantic v2).

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
  * As colunas de **chave natural** (``session_uid``/``service``) e as usadas em
    filtros carregam um ``max_length`` explícito para virarem ``VARCHAR(n)``
    (indexável em UNIQUE) em vez de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo.

Nota crítica sobre a chave de negócio da sessão: a fábrica canônica injeta um
surrogate ``id`` autoincrement como PK. O antigo ``sessions.id`` de negócio
(``sess_<hex>``) vira a coluna própria ``session_uid VARCHAR`` com UNIQUE, e as
tabelas-filho referenciam esse valor por ``session_id VARCHAR`` (o store mapeia
``session_uid`` -> ``id`` na saída, preservando o contrato das tools).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SessionRow(BaseModel):
    """Uma sessão de trabalho (chave natural única: ``session_uid``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    session_uid: str = Field(max_length=64)  # chave natural única -> VARCHAR(64)
    name: str | None = None
    title: str
    objective: str
    repo: str | None = Field(default=None, max_length=255)
    branch: str | None = None
    base_branch: str | None = None
    status: str = Field(default="active", max_length=32)
    progress: str | None = None
    started_at: str | None = None
    last_updated_at: str | None = None
    ended_at: str | None = None


class CheckpointRow(BaseModel):
    """Um snapshot de progresso da sessão (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    session_id: str = Field(max_length=64)
    summary: str
    context_json: str | None = None  # JSON serializado (TEXT)
    created_at: str | None = None


class ArtifactRow(BaseModel):
    """Um artefato/evento da sessão (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    session_id: str = Field(max_length=64)
    type: str = Field(max_length=64)
    content: str
    created_at: str | None = None


class TaskRow(BaseModel):
    """Uma tarefa planejada/executada dentro da sessão (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    session_id: str = Field(max_length=64)
    title: str
    description: str | None = None
    status: str = Field(default="pending", max_length=32)
    sort_order: int | None = None
    result: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None
    needs_human_decision: int | None = None
    decision: str | None = Field(default=None, max_length=16)
    decided_at: str | None = None
    decision_notes: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ServiceDepRow(BaseModel):
    """Um serviço auxiliar vinculado à sessão (chave natural: ``session_id+service``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    session_id: str = Field(max_length=64)
    service: str = Field(max_length=255)
    role: str | None = None
    notes: str | None = None
    added_at: str | None = None


class SuggestionRow(BaseModel):
    """Uma sugestão cross-repo (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    source_repo: str = Field(max_length=255)
    source_session_id: str | None = Field(default=None, max_length=64)
    target_repo: str = Field(max_length=255)
    title: str
    description: str | None = None
    kind: str | None = Field(default=None, max_length=32)
    priority: str | None = Field(default=None, max_length=32)
    status: str = Field(default="pending", max_length=32)
    response_reason: str | None = None
    accepted_session_id: str | None = Field(default=None, max_length=64)
    accepted_task_id: int | None = None
    superseded_by: int | None = None
    created_at: str | None = None
    responded_at: str | None = None


class DecisionRow(BaseModel):
    """Uma entrada do audit trail de decisões (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    actor_type: str = Field(max_length=32)
    actor_id: str = Field(max_length=255)
    action: str = Field(max_length=64)
    target_type: str = Field(max_length=64)
    target_id: str = Field(max_length=255)
    decision: str | None = Field(default=None, max_length=32)
    rationale: str | None = None
    context_json: str | None = None  # JSON serializado (TEXT)
    session_id: str | None = Field(default=None, max_length=64)
    created_at: str | None = None


__all__ = [
    "SessionRow",
    "CheckpointRow",
    "ArtifactRow",
    "TaskRow",
    "ServiceDepRow",
    "SuggestionRow",
    "DecisionRow",
]
