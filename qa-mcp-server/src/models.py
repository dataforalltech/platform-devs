"""Entidade canônica do store do qa-mcp (Pydantic v2).

Dirige DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`) sobre o pool async do tenant.

O qa-mcp persiste UM log append-only de execuções (`test_runs`): cada tool grava UMA
linha (Create) e `generate_qa_report` consulta o histórico (Read). NÃO há chave natural
(múltiplas linhas por (repo_path, run_type) são o histórico esperado), portanto NÃO há
`UniqueConstraintSpec` — diferente do pipeline-mcp (que tem chaves service/env/gate_type).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma escrita pode
    não popular (framework/duration_ms/repo_path).
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``, ``timestamp_refresh``,
    ``scope``) são injetadas pela fábrica de schema / pelas ``EntityConventions`` — NÃO
    são declaradas aqui (seriam ignoradas por colisão).
  * ``run_type``/``status``/``framework`` carregam um ``max_length`` explícito para
    virarem ``VARCHAR(n)`` (indexáveis/curtas) em vez de ``TEXT``. ``repo_path`` fica
    ``TEXT`` (sobrecarregado: guarda repo_path para test/analysis, base_url para api,
    url para browser, ou NULL) — potencialmente longo e sem participação em chave.
  * ``summary``/``details`` são JSON serializado em ``TEXT`` (dual-db safe; não é coluna
    JSON nativa). ``started_at`` é a string ISO de negócio (ordenação do histórico).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TestRunRow(BaseModel):
    """Uma execução registrada no histórico de QA (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    repo_path: str | None = None  # sobrecarregado (repo_path/base_url/url/NULL) -> TEXT
    run_type: str = Field(max_length=64)  # unit|e2e|api|... -> VARCHAR(64)
    framework: str | None = Field(default=None, max_length=64)
    started_at: str | None = None  # string ISO de negócio (ordenação do histórico)
    duration_ms: int | None = None
    status: str = Field(max_length=32)  # passed|failed|error|warning -> VARCHAR(32)
    summary: str | None = None  # JSON serializado (TEXT)
    details: str | None = None  # JSON serializado (TEXT)


__all__ = ["TestRunRow"]
