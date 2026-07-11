"""Entidades canônicas do store do pipeline-mcp (Pydantic v2).

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
  * As colunas de **chave natural** (``service``/``env``/``gate_type``) carregam um
    ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável em UNIQUE) em vez
    de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PipelineRow(BaseModel):
    """Um serviço registrado no pipeline (chave natural única: ``service``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    service: str = Field(max_length=255)  # chave natural única -> VARCHAR(255)
    repo: str | None = None
    base_branch: str | None = None
    current_env: str | None = Field(default=None, max_length=32)
    current_version: str | None = None
    blocked: int | None = None
    block_reason: str | None = None
    blocked_by: str | None = None
    blocked_at: str | None = None
    gates_config: str | None = None  # JSON serializado (TEXT)
    registered_at: str | None = None
    updated_at: str | None = None


class PromotionRow(BaseModel):
    """Uma promoção entre ambientes (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    service: str = Field(max_length=255)
    from_env: str | None = Field(default=None, max_length=32)
    to_env: str | None = Field(default=None, max_length=32)
    promoted_by: str | None = None
    reason: str | None = None
    gates_snapshot: str | None = None  # JSON serializado (TEXT)
    deploy_ref: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    status: str | None = Field(default=None, max_length=32)
    created_at: str | None = None
    completed_at: str | None = None


class GateRow(BaseModel):
    """Resultado de um gate de qualidade (chave natural única: ``service+env+gate_type``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    service: str = Field(max_length=255)
    env: str = Field(max_length=32)
    gate_type: str = Field(max_length=64)
    passed: int | None = None
    details: str | None = None
    evaluated_by: str | None = None
    evaluated_at: str | None = None


__all__ = ["PipelineRow", "PromotionRow", "GateRow"]
