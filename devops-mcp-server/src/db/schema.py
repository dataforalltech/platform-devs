"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). As tabelas com **chave natural** são `devops_environments` (um por
`name`) e `devops_service_configs` (um por `service`) — cada uma ganha uma constraint
UNIQUE de tabela, renderizada DENTRO do `CREATE TABLE IF NOT EXISTS` (idempotente, sem
`CREATE INDEX` avulso que quebraria no re-run). O `upsert` do Repository (INSERT ...
ON DUPLICATE KEY UPDATE no MySQL / ON CONFLICT no PG) depende dessas UNIQUE existirem.

As demais tabelas (artifacts/pipelines/deployments) são históricos com chave
surrogate `id` — múltiplas linhas por (target/application/...) são o histórico
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
    DeploymentRow,
    DevopsArtifactRow,
    EnvironmentRow,
    PipelineRow,
    ServiceConfigRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
ARTIFACTS_TABLE = "devops_artifacts"
PIPELINES_TABLE = "devops_pipelines"
DEPLOYMENTS_TABLE = "devops_deployments"
ENVIRONMENTS_TABLE = "devops_environments"
SERVICE_CONFIGS_TABLE = "devops_service_configs"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 5 tabelas do devops (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(DevopsArtifactRow, table_name=ARTIFACTS_TABLE),
            create_table_from_model(PipelineRow, table_name=PIPELINES_TABLE),
            create_table_from_model(DeploymentRow, table_name=DEPLOYMENTS_TABLE),
            _with_uniques(
                EnvironmentRow,
                ENVIRONMENTS_TABLE,
                unique=["name"],
                unique_name="uq_devops_environments_name",
            ),
            _with_uniques(
                ServiceConfigRow,
                SERVICE_CONFIGS_TABLE,
                unique=["service"],
                unique_name="uq_devops_service_configs_service",
            ),
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
    "ARTIFACTS_TABLE",
    "PIPELINES_TABLE",
    "DEPLOYMENTS_TABLE",
    "ENVIRONMENTS_TABLE",
    "SERVICE_CONFIGS_TABLE",
    "build_migration",
    "ensure_schema",
]
