"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). A única tabela com **chave natural** é `qa_quality_gates` (um gate por
serviço) — ela ganha uma constraint UNIQUE de tabela sobre `service`, renderizada
DENTRO do `CREATE TABLE IF NOT EXISTS` (idempotente, sem `CREATE INDEX` avulso que
quebraria no re-run). O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no
MySQL / ON CONFLICT no PG) depende dessa UNIQUE existir.

As demais tabelas (plans/cases/bugs/artifacts) são históricos com chave surrogate
`id` — múltiplas linhas por (feature/target/...) são o histórico esperado, portanto
sem `UniqueConstraintSpec`.

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
    QaArtifactRow,
    QualityGateRow,
    TestCaseRow,
    TestPlanRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
TEST_PLANS_TABLE = "qa_test_plans"
TEST_CASES_TABLE = "qa_test_cases"
BUG_REPORTS_TABLE = "qa_bug_reports"
QUALITY_GATES_TABLE = "qa_quality_gates"
ARTIFACTS_TABLE = "qa_artifacts"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 5 tabelas do qa-engineer (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(TestPlanRow, table_name=TEST_PLANS_TABLE),
            create_table_from_model(TestCaseRow, table_name=TEST_CASES_TABLE),
            create_table_from_model(BugReportRow, table_name=BUG_REPORTS_TABLE),
            _with_uniques(
                QualityGateRow,
                QUALITY_GATES_TABLE,
                unique=["service"],
                unique_name="uq_qa_quality_gates_service",
            ),
            create_table_from_model(QaArtifactRow, table_name=ARTIFACTS_TABLE),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 5 tabelas no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "TEST_PLANS_TABLE",
    "TEST_CASES_TABLE",
    "BUG_REPORTS_TABLE",
    "QUALITY_GATES_TABLE",
    "ARTIFACTS_TABLE",
    "build_migration",
    "ensure_schema",
]
