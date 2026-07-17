"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). Há DUAS tabelas com **chave natural**: `backend_api_contracts` (um
contrato por endpoint+verbo) ganha uma UNIQUE composta sobre `(endpoint, method)`; e
`backend_auth_policies` (uma política por recurso) ganha uma UNIQUE sobre `resource`.
Ambas são renderizadas DENTRO do `CREATE TABLE IF NOT EXISTS` (idempotente, sem
`CREATE INDEX` avulso que quebraria no re-run). O `upsert` do Repository (INSERT ...
ON DUPLICATE KEY UPDATE no MySQL / ON CONFLICT no PG) depende dessas UNIQUE existirem.

As demais tabelas (database_schemas/artifacts/code_reviews) são históricos com chave
surrogate `id` — múltiplas linhas por (entity/target/...) são o histórico esperado,
portanto sem `UniqueConstraintSpec`.

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
    APIContractRow,
    AuthPolicyRow,
    BackendArtifactRow,
    CodeReviewRow,
    DatabaseSchemaRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
API_CONTRACTS_TABLE = "backend_api_contracts"
DATABASE_SCHEMAS_TABLE = "backend_database_schemas"
AUTH_POLICIES_TABLE = "backend_auth_policies"
ARTIFACTS_TABLE = "backend_artifacts"
CODE_REVIEWS_TABLE = "backend_code_reviews"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 5 tabelas do backend (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_uniques(
                APIContractRow,
                API_CONTRACTS_TABLE,
                unique=["endpoint", "method"],
                unique_name="uq_backend_api_contracts_endpoint_method",
            ),
            create_table_from_model(DatabaseSchemaRow, table_name=DATABASE_SCHEMAS_TABLE),
            _with_uniques(
                AuthPolicyRow,
                AUTH_POLICIES_TABLE,
                unique=["resource"],
                unique_name="uq_backend_auth_policies_resource",
            ),
            create_table_from_model(BackendArtifactRow, table_name=ARTIFACTS_TABLE),
            create_table_from_model(CodeReviewRow, table_name=CODE_REVIEWS_TABLE),
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
    "API_CONTRACTS_TABLE",
    "DATABASE_SCHEMAS_TABLE",
    "AUTH_POLICIES_TABLE",
    "ARTIFACTS_TABLE",
    "CODE_REVIEWS_TABLE",
    "build_migration",
    "ensure_schema",
]
