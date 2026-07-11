"""Entidades canônicas do store do audit-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

O modelo antigo guardava UMA tabela `audit_log` com `items[]` e `approvals[]`
aninhados num blob JSON `checklist`. Aqui isso é NORMALIZADO em quatro tabelas:

  * ``audits``               — a auditoria (score, status, checklist opaco);
  * ``audit_items``          — os itens do checklist (1-N por auditoria);
  * ``audit_approvals``      — as aprovações/rejeições (1-N por auditoria);
  * ``service_criticality``  — a criticidade por serviço (antes um stub NO-OP).

Convenções (playbook §5):

  * O ``id`` surrogate (INT autoincrement) é injetado pela fábrica de schema — a chave
    natural do domínio é a string determinística ``audit_key`` (``audit_<service>_<env>``),
    preservada com UNIQUE para o contrato público de ``audit_id`` seguir sendo string.
  * As colunas padrão (``id``, ``id_user_created``, ``id_user_modify``, ``create_on``,
    ``active``, ``excluded``, ``timestamp_refresh``, ``scope``) são injetadas pela
    fábrica / pelas ``EntityConventions`` — NÃO são declaradas aqui.
  * As colunas de **chave natural** (``audit_key`` / ``service``) e os ponteiros usados
    em filtro (``audit_id``, ``env``, ...) carregam ``max_length`` explícito para virarem
    ``VARCHAR(n)`` (indexável em UNIQUE) em vez de ``TEXT`` — MySQL não indexa ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuditRow(BaseModel):
    """Uma auditoria de compliance (chave natural única: ``audit_key``).

    ``audit_key`` é a string determinística ``audit_<service>_<env>`` — é o
    ``audit_id`` que o cliente vê (contrato mantido como string). O ``id`` surrogate
    (INT) é interno; o round-trip público expõe ``audit_key`` como ``id``.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    audit_key: str = Field(max_length=255)  # chave natural única -> VARCHAR(255)
    service: str = Field(max_length=255)
    repo: str | None = None
    env: str = Field(max_length=32)
    criticality: str | None = Field(default=None, max_length=32)
    score: float | None = None
    passed: int | None = None  # 0/1
    status: str | None = Field(default=None, max_length=32)
    checklist: str | None = None  # JSON serializado (TEXT), back-compat opaco
    created_at: str | None = None
    updated_at: str | None = None


class AuditItemRow(BaseModel):
    """Um item do checklist de uma auditoria (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    audit_id: str = Field(max_length=255)  # -> audits.audit_key
    category: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    required: int | None = None  # 0/1
    passed: int | None = None  # 0/1
    details: str | None = None


class AuditApprovalRow(BaseModel):
    """Uma aprovação/rejeição manual de uma auditoria (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    audit_id: str = Field(max_length=255)  # -> audits.audit_key
    approved_by: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=64)
    decision: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    created_at: str | None = None


class ServiceCriticalityRow(BaseModel):
    """A criticidade declarada de um serviço (chave natural única: ``service``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    service: str = Field(max_length=255)  # chave natural única -> VARCHAR(255)
    criticality: str | None = Field(default=None, max_length=32)
    updated_by: str | None = Field(default=None, max_length=255)
    updated_at: str | None = None


__all__ = ["AuditRow", "AuditItemRow", "AuditApprovalRow", "ServiceCriticalityRow"]
