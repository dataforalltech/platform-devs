"""Entidades canônicas do store do docs-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`upsert`/`delete_where`) sobre o
     pool async do tenant.

A migração desfaz o anti-pattern do store legado (uma tabela única `documents`
sobrecarregada por um discriminador `doc_type` + blob JSON na coluna `content`): as
duas entidades lógicas viram DUAS tabelas limpas — `audits` (histórico de auditoria)
e `doc_index` (índice de documentos). Os campos antes enfiados no blob `content` e na
coluna `title` são promovidos a COLUNAS reais.

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas de **chave natural** (``repo_path``/``file_path``) carregam um
    ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável em UNIQUE) em vez
    de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho. Os limites somados
    (500 + 255 = 755 chars → 3020 bytes utf8mb4) ficam abaixo do teto de índice do
    InnoDB (3072 bytes).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuditRow(BaseModel):
    """Uma auditoria de documentação de um repositório (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    repo_path: str = Field(max_length=500)  # filtro por repo -> VARCHAR(500)
    score: int | None = None
    grade: str | None = Field(default=None, max_length=2)
    summary: str | None = None  # JSON serializado (TEXT)
    details: str | None = None  # JSON serializado (TEXT)
    duration_ms: int | None = None
    created_at: str | None = None


class DocIndexRow(BaseModel):
    """Um documento indexado (chave natural única: ``repo_path`` + ``file_path``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    repo_path: str = Field(max_length=500)  # chave natural -> VARCHAR(500)
    file_path: str = Field(max_length=255)  # chave natural -> VARCHAR(255)
    doc_type: str | None = Field(default=None, max_length=32)
    doc_title: str | None = None  # título humano do doc (TEXT)
    word_count: int | None = None
    last_modified: str | None = None
    content_hash: str | None = Field(default=None, max_length=32)  # md5 hex = 32
    created_at: str | None = None


__all__ = ["AuditRow", "DocIndexRow"]
