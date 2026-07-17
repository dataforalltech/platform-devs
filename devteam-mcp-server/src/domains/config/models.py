"""Entidades canônicas do store do config-mcp (Pydantic v2).

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
  * As colunas de **chave natural** (``namespace``/``config_key``) carregam um
    ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável em UNIQUE) em vez
    de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho.
  * ``config_key`` (não ``key``): ``KEY`` é palavra reservada no MySQL e os
    identificadores saem UNQUOTED do dialeto; a superfície MCP continua devolvendo
    ``key`` (o store reshape a coluna → contrato).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConfigEntryRow(BaseModel):
    """Uma entrada de configuração encriptada (chave natural única: ``namespace+config_key``).

    O ``value_encrypted`` guarda a CIFRA Fernet (nunca texto claro): a encriptação
    at-rest é ortogonal ao banco — o Encryptor permanece na app (defense-in-depth,
    DBAs/admin não leem segredos), o ORM só persiste TEXT opaco.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    namespace: str = Field(max_length=255)  # chave natural (parte 1) -> VARCHAR(255)
    config_key: str = Field(max_length=255)  # chave natural (parte 2) -> VARCHAR(255)
    value_encrypted: str | None = None  # cifra Fernet (TEXT)
    description: str | None = None  # documentação opcional (TEXT)


__all__ = ["ConfigEntryRow"]
