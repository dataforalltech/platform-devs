"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma) e, onde há chave natural, ganha as **constraints UNIQUE** como
constraints de tabela — renderizadas DENTRO do `CREATE TABLE IF NOT EXISTS`, portanto
idempotentes (criadas só junto com a tabela, sem `CREATE INDEX` separado que quebraria
no re-run).

O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL / ON CONFLICT no
PG) depende dessas UNIQUE existirem — é o que torna o resultado de item upsertable por
(run_id, item_id).

Idempotente e multi-engine: `emit_ddl(script, engine)` compila para o dialeto do
tenant (mysql/postgresql), então o MESMO bootstrap serve o dual-db.
"""

from __future__ import annotations

from typing import Any

from platform_database.orm.ddl import (
    CreateTable,
    MigrationScript,
    UniqueConstraintSpec,
    create_table_from_model,
    emit_ddl,
)

from ..models import (
    BugReportRow,
    ChecklistItemRow,
    ChecklistResultRow,
    ChecklistRow,
    ChecklistRunRow,
    ScenarioRow,
    TestCaseRow,
    TestPlanRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
TEST_PLANS_TABLE = "test_plans"
TEST_SCENARIOS_TABLE = "test_scenarios"
TEST_CASES_TABLE = "test_cases"
BUG_REPORTS_TABLE = "bug_reports"
CHECKLISTS_TABLE = "checklists"  # renomeado de quality_gates
CHECKLIST_ITEMS_TABLE = "checklist_items"
CHECKLIST_RUNS_TABLE = "checklist_runs"
CHECKLIST_RESULTS_TABLE = "checklist_results"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 8 tabelas do test-mcp (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(TestPlanRow, table_name=TEST_PLANS_TABLE),
            create_table_from_model(ScenarioRow, table_name=TEST_SCENARIOS_TABLE),
            create_table_from_model(TestCaseRow, table_name=TEST_CASES_TABLE),
            create_table_from_model(BugReportRow, table_name=BUG_REPORTS_TABLE),
            create_table_from_model(ChecklistRow, table_name=CHECKLISTS_TABLE),
            create_table_from_model(ChecklistItemRow, table_name=CHECKLIST_ITEMS_TABLE),
            _with_uniques(
                ChecklistRunRow,
                CHECKLIST_RUNS_TABLE,
                unique=["run_id"],
                unique_name="uq_checklist_runs_run_id",
            ),
            _with_uniques(
                ChecklistResultRow,
                CHECKLIST_RESULTS_TABLE,
                unique=["run_id", "item_id"],
                unique_name="uq_checklist_results_run_item",
            ),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 8 tabelas no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "TEST_PLANS_TABLE",
    "TEST_SCENARIOS_TABLE",
    "TEST_CASES_TABLE",
    "BUG_REPORTS_TABLE",
    "CHECKLISTS_TABLE",
    "CHECKLIST_ITEMS_TABLE",
    "CHECKLIST_RUNS_TABLE",
    "CHECKLIST_RESULTS_TABLE",
    "build_migration",
    "ensure_schema",
]
