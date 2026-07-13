"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). A única tabela com **chave natural** é `arch_c4_diagrams` (um modelo C4
por sistema) — ela ganha uma constraint UNIQUE de tabela sobre `system_name`,
renderizada DENTRO do `CREATE TABLE IF NOT EXISTS` (idempotente, sem `CREATE INDEX`
avulso que quebraria no re-run). O `upsert` do Repository (INSERT ... ON DUPLICATE KEY
UPDATE no MySQL / ON CONFLICT no PG) depende dessa UNIQUE existir.

As demais tabelas (blueprints/solutions/artifacts) são históricos com chave surrogate
`id` — múltiplas linhas por (domain/solution_name/target/...) são o histórico
esperado, portanto sem `UniqueConstraintSpec`.

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
    ArchitectureArtifactRow,
    ArchitectureBlueprintRow,
    C4DiagramRow,
    SolutionBlueprintRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
ARCHITECTURE_BLUEPRINTS_TABLE = "arch_architecture_blueprints"
C4_DIAGRAMS_TABLE = "arch_c4_diagrams"
SOLUTION_BLUEPRINTS_TABLE = "arch_solution_blueprints"
ARTIFACTS_TABLE = "arch_artifacts"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 4 tabelas do architecture (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(ArchitectureBlueprintRow, table_name=ARCHITECTURE_BLUEPRINTS_TABLE),
            _with_uniques(
                C4DiagramRow,
                C4_DIAGRAMS_TABLE,
                unique=["system_name"],
                unique_name="uq_arch_c4_diagrams_system_name",
            ),
            create_table_from_model(SolutionBlueprintRow, table_name=SOLUTION_BLUEPRINTS_TABLE),
            create_table_from_model(ArchitectureArtifactRow, table_name=ARTIFACTS_TABLE),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 4 tabelas no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "ARCHITECTURE_BLUEPRINTS_TABLE",
    "C4_DIAGRAMS_TABLE",
    "SOLUTION_BLUEPRINTS_TABLE",
    "ARTIFACTS_TABLE",
    "build_migration",
    "ensure_schema",
]
