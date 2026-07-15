"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). As tabelas com **chave natural** são `po_mvp_scopes` e
`po_product_visions` (um por produto) — cada uma ganha uma constraint UNIQUE de
tabela sobre `product`, renderizada DENTRO do `CREATE TABLE IF NOT EXISTS`
(idempotente, sem `CREATE INDEX` avulso que quebraria no re-run). O `upsert` do
Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL / ON CONFLICT no PG) depende
dessa UNIQUE existir.

As demais tabelas (user_stories/user_personas/backlog_items/artifacts) são históricos
com chave surrogate `id` — múltiplas linhas por (feature/name/...) são o histórico
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
    BacklogItemRow,
    MVPScopeRow,
    PoArtifactRow,
    ProductVisionRow,
    UserPersonaRow,
    UserStoryRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
USER_STORIES_TABLE = "po_user_stories"
MVP_SCOPES_TABLE = "po_mvp_scopes"
PRODUCT_VISIONS_TABLE = "po_product_visions"
USER_PERSONAS_TABLE = "po_user_personas"
BACKLOG_ITEMS_TABLE = "po_backlog_items"
ARTIFACTS_TABLE = "po_artifacts"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 6 tabelas do product-owner (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(UserStoryRow, table_name=USER_STORIES_TABLE),
            _with_uniques(
                MVPScopeRow,
                MVP_SCOPES_TABLE,
                unique=["product"],
                unique_name="uq_po_mvp_scopes_product",
            ),
            _with_uniques(
                ProductVisionRow,
                PRODUCT_VISIONS_TABLE,
                unique=["product"],
                unique_name="uq_po_product_visions_product",
            ),
            create_table_from_model(UserPersonaRow, table_name=USER_PERSONAS_TABLE),
            create_table_from_model(BacklogItemRow, table_name=BACKLOG_ITEMS_TABLE),
            create_table_from_model(PoArtifactRow, table_name=ARTIFACTS_TABLE),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 6 tabelas no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "USER_STORIES_TABLE",
    "MVP_SCOPES_TABLE",
    "PRODUCT_VISIONS_TABLE",
    "USER_PERSONAS_TABLE",
    "BACKLOG_ITEMS_TABLE",
    "ARTIFACTS_TABLE",
    "build_migration",
    "ensure_schema",
]
