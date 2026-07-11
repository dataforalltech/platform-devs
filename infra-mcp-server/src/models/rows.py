"""Entidades canônicas (row models) do AllocatorStore — Pydantic v2.

Estes modelos dirigem DUAS camadas do ORM canônico (``platform_database.orm``):

  1. **DDL IR** — ``create_table_from_model`` gera o ``CREATE TABLE`` (com as colunas
     padrão da plataforma injetadas pela ``schema.table_factory``).
  2. **Repository** — CRUD tipado (``find``/``insert``/``update_where``/``delete_where``)
     sobre o pool async do tenant.

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura pode
    não popular (``NULL`` no DDL).
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``, ``timestamp_refresh``,
    ``scope``) são injetadas pela fábrica de schema / pelas ``EntityConventions`` — NÃO
    são declaradas aqui (seriam ignoradas por colisão). O ``id`` surrogate int é a PK;
    os IDs de negócio (``vm_id``/``lease_id``/``request_id``) viram **coluna de chave
    natural única** (UNIQUE de tabela em ``schema.py``), com ``max_length`` explícito ⇒
    ``VARCHAR(n)`` indexável (MySQL não indexa ``TEXT`` sem prefixo).
  * Datetimes são serializados como **TEXT ISO-8601** (colunas ``*_at``), exatamente
    como o store SQLite fazia — o store converte para/de ``datetime`` do domínio.
  * ``encrypted_private_key`` é ``bytes`` ⇒ ``BLOB`` (MySQL) / ``BYTEA`` (PostgreSQL):
    ciphertext Fernet da chave privada Ed25519, cifrado na camada de app.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VmRow(BaseModel):
    """Uma VM no pool (chave natural única: ``vm_id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    vm_id: str = Field(max_length=64)  # chave natural única -> VARCHAR(64)
    spec: str = Field(max_length=32)
    status: str = Field(max_length=32)
    created_at: str  # ISO-8601 (TEXT)
    exclusive_locked_by: str | None = Field(default=None, max_length=64)
    connection_hint: str | None = None


class LeaseRow(BaseModel):
    """Uma concessão de slot a um agente (chave natural única: ``lease_id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    lease_id: str = Field(max_length=64)  # chave natural única -> VARCHAR(64)
    vm_id: str = Field(max_length=64)
    spec: str = Field(max_length=32)
    owner: str = Field(max_length=255)
    purpose: str | None = None
    status: str = Field(max_length=32)
    exclusive: int
    priority: str = Field(max_length=16)
    created_at: str
    expires_at: str
    released_at: str | None = None
    extension_count: int
    connection_hint: str | None = None


class VmKeyRow(BaseModel):
    """Chave privada SSH cifrada (Fernet) por VM (chave natural única 1:1: ``vm_id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    vm_id: str = Field(max_length=64)  # chave natural única (1:1 com vms) -> VARCHAR(64)
    encrypted_private_key: bytes  # ciphertext Fernet -> BLOB/BYTEA
    public_key: str
    created_at: str


class QueuedRequestRow(BaseModel):
    """Um request bloqueado pelo cost cap, persistido na fila (chave natural: ``request_id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    request_id: str = Field(max_length=64)  # chave natural única -> VARCHAR(64)
    spec: str = Field(max_length=32)
    duration_min: int
    owner: str = Field(max_length=255)
    purpose: str | None = None
    exclusive: int
    priority: str = Field(max_length=16)
    human_approved: int
    created_at: str
    status: str = Field(max_length=32)


__all__ = ["VmRow", "LeaseRow", "VmKeyRow", "QueuedRequestRow"]
