"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). A única tabela com **chave natural** é `pm_product_visions` (uma visão
por produto) — ela ganha uma constraint UNIQUE de tabela sobre `product`, renderizada
DENTRO do `CREATE TABLE IF NOT EXISTS` (idempotente, sem `CREATE INDEX` avulso que
quebraria no re-run). O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no
MySQL / ON CONFLICT no PG) depende dessa UNIQUE existir.

As demais tabelas (feature_specs/gtm_briefs/release_plans/artifacts) são históricos
com chave surrogate `id` — múltiplas linhas por (feature/product/target/...) são o
histórico esperado, portanto sem `UniqueConstraintSpec`.

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
    FeatureSpecRow,
    GtmBriefRow,
    PmArtifactRow,
    ProductVisionRow,
    ReleasePlanRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
FEATURE_SPECS_TABLE = "pm_feature_specs"
GTM_BRIEFS_TABLE = "pm_gtm_briefs"
RELEASE_PLANS_TABLE = "pm_release_plans"
PRODUCT_VISIONS_TABLE = "pm_product_visions"
ARTIFACTS_TABLE = "pm_artifacts"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 5 tabelas do product-manager (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(FeatureSpecRow, table_name=FEATURE_SPECS_TABLE),
            create_table_from_model(GtmBriefRow, table_name=GTM_BRIEFS_TABLE),
            create_table_from_model(ReleasePlanRow, table_name=RELEASE_PLANS_TABLE),
            _with_uniques(
                ProductVisionRow,
                PRODUCT_VISIONS_TABLE,
                unique=["product"],
                unique_name="uq_pm_product_visions_product",
            ),
            create_table_from_model(PmArtifactRow, table_name=ARTIFACTS_TABLE),
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
    "FEATURE_SPECS_TABLE",
    "GTM_BRIEFS_TABLE",
    "RELEASE_PLANS_TABLE",
    "PRODUCT_VISIONS_TABLE",
    "ARTIFACTS_TABLE",
    "build_migration",
    "ensure_schema",
]
