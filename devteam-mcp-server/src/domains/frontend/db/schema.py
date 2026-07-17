"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). A única tabela com **chave natural** é `fe_pages` (uma página por
rota) — ela ganha uma constraint UNIQUE de tabela sobre `route`, renderizada
DENTRO do `CREATE TABLE IF NOT EXISTS` (idempotente, sem `CREATE INDEX` avulso que
quebraria no re-run). O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no
MySQL / ON CONFLICT no PG) depende dessa UNIQUE existir.

As demais tabelas (components/forms/stories/artifacts) são históricos com chave
surrogate `id` — múltiplas linhas por (name/component/target/...) são o histórico
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
    ComponentRow,
    FormRow,
    FrontendArtifactRow,
    PageRow,
    StoryRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
COMPONENTS_TABLE = "fe_components"
PAGES_TABLE = "fe_pages"
FORMS_TABLE = "fe_forms"
STORIES_TABLE = "fe_stories"
ARTIFACTS_TABLE = "fe_artifacts"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 5 tabelas do frontend (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(ComponentRow, table_name=COMPONENTS_TABLE),
            _with_uniques(
                PageRow,
                PAGES_TABLE,
                unique=["route"],
                unique_name="uq_fe_pages_route",
            ),
            create_table_from_model(FormRow, table_name=FORMS_TABLE),
            create_table_from_model(StoryRow, table_name=STORIES_TABLE),
            create_table_from_model(FrontendArtifactRow, table_name=ARTIFACTS_TABLE),
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
    "COMPONENTS_TABLE",
    "PAGES_TABLE",
    "FORMS_TABLE",
    "STORIES_TABLE",
    "ARTIFACTS_TABLE",
    "build_migration",
    "ensure_schema",
]
