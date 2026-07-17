"""Entidades canônicas do store do dev-twin-mcp (Pydantic v2).

Este modelo dirige DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update_where`/`delete_where`)
     sobre o pool async do tenant.

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
    A **revogação** é o soft-delete canônico (``excluded=1``); reads filtram
    ``excluded=0``, logo tokens revogados somem de validate/list.
  * As colunas de **chave natural / lookup** (``token``/``token_prefix``/``user_id``)
    carregam um ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável em
    UNIQUE) em vez de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho.
  * Timestamps de negócio (``created_at``/``last_used_at``/``expires_at``) são
    strings ISO em colunas próprias (padrão do pipeline: ``registered_at``/
    ``updated_at``), independentes do ``create_on``/``timestamp_refresh`` canônicos.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentTokenRow(BaseModel):
    """Um token de agente/usuário (chave natural única: ``token`` = bcrypt hash).

    O ``token`` guardado é SEMPRE o hash bcrypt (nunca plaintext). ``token_prefix``
    (8 primeiros chars do token original) é a chave de lookup rápido de validate().
    ``user_id`` é a chave funcional de revoke/rotate/touch (assume 1 token vivo por
    user_id; não declarada UNIQUE porque há N linhas revogadas/soft-deletadas por
    user_id — o "1 ativo" é garantido pela app, não por índice único parcial que o
    MySQL não suporta). ``tenant_id`` aqui é o tenant PADRÃO do usuário (atributo do
    token), NÃO a dimensão de isolamento — esta última vem sempre dos claims do
    inner token e escopa o próprio banco (banco-por-tenant).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    token: str = Field(max_length=255)  # bcrypt hash, chave natural única -> VARCHAR(255)
    token_prefix: str | None = Field(default=None, max_length=16)  # lookup key -> VARCHAR(16)
    user_id: str = Field(max_length=64)  # chave funcional (revoke/rotate/touch) -> VARCHAR(64)
    name: str | None = None
    email: str | None = None
    role: str | None = Field(default=None, max_length=32)
    scopes: str | None = None  # JSON serializado (TEXT)
    environment: str | None = Field(default=None, max_length=32)
    tenant_id: str | None = Field(default=None, max_length=255)  # tenant padrão do usuário (atributo)
    created_at: str | None = None  # ISO string (coluna própria, não o create_on canônico)
    last_used_at: str | None = None
    expires_at: str | None = None  # ISO string; NULL = sem expiração


__all__ = ["AgentTokenRow"]
