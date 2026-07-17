"""Entidades canônicas do store do test-mcp (Pydantic v2).

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
  * As colunas de **chave natural** (``run_id``/``checklist_id``) carregam um
    ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável em UNIQUE) em vez
    de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho.

Renomeações vs o schema PG legado (evitam colisão com coluna padrão / palavra reservada):
  * ``test_plans.scope``  -> ``test_plans.plan_scope`` (``scope`` é coluna padrão da
    plataforma; o valor de domínio do plano viaja em ``plan_scope``, remapeado para
    ``scope`` na saída do store).
  * ``quality_gates``     -> ``checklists`` (a tabela sempre foi um cabeçalho de
    checklist, mal-nomeada); a coluna ``type`` vira ``checklist_type``.
  * ``checklist_runs.id`` (TEXT natural ``run_`` + uuid) -> ``run_id`` (VARCHAR UNIQUE);
    o ``id`` surrogate INT é injetado pela fábrica.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TestPlanRow(BaseModel):
    """Um plano de testes (raiz do agregado; chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    title: str | None = None
    # Domínio "scope" do plano — coluna física ``plan_scope`` (a coluna padrão
    # ``scope`` é reservada pela plataforma). Remapeada para ``scope`` na saída.
    plan_scope: str | None = None
    feature: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ScenarioRow(BaseModel):
    """Um cenário de teste vinculado a um plano (FK lógica ``plan_id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    plan_id: int | None = None
    name: str | None = None
    category: str | None = None
    priority: str | None = None
    preconditions: str | None = None
    steps: str | None = None
    expected_result: str | None = None
    created_at: str | None = None


class TestCaseRow(BaseModel):
    """Um resultado de execução de cenário (append-only; histórico por ``executed_at``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    plan_id: int | None = None
    scenario_id: int | None = None
    status: str | None = None
    actual_result: str | None = None
    notes: str | None = None
    evidence: str | None = None
    executed_at: str | None = None


class BugReportRow(BaseModel):
    """Um bug/finding vinculado a um plano (exposto como ``add_bug``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    plan_id: int | None = None
    severity: str | None = None
    title: str | None = None
    description: str | None = None
    evidence: str | None = None
    status: str | None = None
    created_at: str | None = None


class ChecklistRow(BaseModel):
    """Cabeçalho de checklist (tabela física ``checklists``; ``type`` -> ``checklist_type``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    title: str | None = None
    checklist_type: str | None = None
    plan_id: int | None = None
    created_at: str | None = None


class ChecklistItemRow(BaseModel):
    """Um item de checklist (correlaciona com ``checklists.id`` via ``checklist_id`` string)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    checklist_id: str = Field(max_length=64)  # correlação por string -> VARCHAR(64)
    order_num: int | None = None
    description: str | None = None
    required: int | None = None  # boolean 0/1
    category: str | None = None


class ChecklistRunRow(BaseModel):
    """Uma execução (run) de checklist (chave natural única: ``run_id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    run_id: str = Field(max_length=64)  # chave natural única -> VARCHAR(64)
    checklist_id: str = Field(max_length=64)
    status: str | None = None
    executor: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ChecklistResultRow(BaseModel):
    """Resultado de um item numa run (chave natural única: ``run_id + item_id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    run_id: str = Field(max_length=64)  # (run_id, item_id) UNIQUE -> upsert
    item_id: int
    status: str | None = None
    notes: str | None = None
    checked_at: str | None = None


__all__ = [
    "TestPlanRow",
    "ScenarioRow",
    "TestCaseRow",
    "BugReportRow",
    "ChecklistRow",
    "ChecklistItemRow",
    "ChecklistRunRow",
    "ChecklistResultRow",
]
