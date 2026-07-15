"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de ``CREATE TABLE`` escrito à mão: cada tabela é um ``CreateTable`` derivado do
modelo Pydantic (``create_table_from_model``, que injeta as colunas padrão da
plataforma). As tabelas com **chave natural** ganham uma constraint UNIQUE de tabela
renderizada DENTRO do ``CREATE TABLE IF NOT EXISTS`` (idempotente) — o ``upsert`` do
Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL / ON CONFLICT no PG) depende
dela existir:

  * ``deploy_pull_requests``  → UNIQUE (repo, number)
  * ``deploy_branches``       → UNIQUE (repo, branch)
  * ``deploy_workflow_runs``  → UNIQUE (repo, run_id)
  * ``deploy_repos``          → UNIQUE (repo)

As demais (``deploy_deployments`` / ``deploy_events``) são históricos append-only com
chave surrogate ``id`` (múltiplas linhas são o histórico esperado) — sem UNIQUE.

Idempotente e multi-engine: ``emit_ddl(script, engine)`` compila para o dialeto do
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

from .models import (
    BranchRow,
    DeployEventRow,
    DeploymentRow,
    PullRequestRow,
    RepoRow,
    WorkflowRunRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
DEPLOYMENTS_TABLE = "deploy_deployments"
PULL_REQUESTS_TABLE = "deploy_pull_requests"
BRANCHES_TABLE = "deploy_branches"
WORKFLOW_RUNS_TABLE = "deploy_workflow_runs"
REPOS_TABLE = "deploy_repos"
EVENTS_TABLE = "deploy_events"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """``CreateTable`` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 6 tabelas do ledger do deploy-mcp (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(DeploymentRow, table_name=DEPLOYMENTS_TABLE),
            _with_uniques(
                PullRequestRow,
                PULL_REQUESTS_TABLE,
                unique=["repo", "number"],
                unique_name="uq_deploy_pull_requests_repo_number",
            ),
            _with_uniques(
                BranchRow,
                BRANCHES_TABLE,
                unique=["repo", "branch"],
                unique_name="uq_deploy_branches_repo_branch",
            ),
            _with_uniques(
                WorkflowRunRow,
                WORKFLOW_RUNS_TABLE,
                unique=["repo", "run_id"],
                unique_name="uq_deploy_workflow_runs_repo_run_id",
            ),
            _with_uniques(
                RepoRow,
                REPOS_TABLE,
                unique=["repo"],
                unique_name="uq_deploy_repos_repo",
            ),
            create_table_from_model(DeployEventRow, table_name=EVENTS_TABLE),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 6 tabelas no banco do tenant (idempotente ``IF NOT EXISTS``).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "DEPLOYMENTS_TABLE",
    "PULL_REQUESTS_TABLE",
    "BRANCHES_TABLE",
    "WORKFLOW_RUNS_TABLE",
    "REPOS_TABLE",
    "EVENTS_TABLE",
    "build_migration",
    "ensure_schema",
]
