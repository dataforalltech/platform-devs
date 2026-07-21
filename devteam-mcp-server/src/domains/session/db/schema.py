"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma) e ganha as **constraints UNIQUE de chave natural** como constraints de
tabela — renderizadas DENTRO do `CREATE TABLE IF NOT EXISTS`, portanto idempotentes
(criadas só junto com a tabela, sem `CREATE INDEX` separado que quebraria no re-run).

O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL) depende dessas
UNIQUE existirem — é o que torna a sessão upsertable por (session_uid) e o vínculo de
serviço por (session_id, service).

Idempotente e multi-engine: `emit_ddl(script, engine)` compila para o dialeto do
tenant (mysql/postgresql), então o MESMO bootstrap serve o dual-db.
"""

from __future__ import annotations

import logging
from typing import Any

from platform_database.orm.ddl import (
    AddColumn,
    ColumnDef,
    CreateTable,
    MigrationScript,
    UniqueConstraintSpec,
    create_table_from_model,
    emit_ddl,
)

from ..models import (
    ArtifactRow,
    CheckpointRow,
    DecisionRow,
    ServiceDepRow,
    SessionRow,
    SuggestionRow,
    TaskRow,
)

_log = logging.getLogger(__name__)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
SESSIONS_TABLE = "sessions"
CHECKPOINTS_TABLE = "checkpoints"
ARTIFACTS_TABLE = "artifacts"
TASKS_TABLE = "tasks"
SESSION_SERVICES_TABLE = "session_services"
SUGGESTIONS_TABLE = "suggestions"
DECISIONS_TABLE = "decisions"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 7 tabelas do session-mcp (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_uniques(
                SessionRow,
                SESSIONS_TABLE,
                unique=["session_uid"],
                unique_name="uq_sessions_uid",
            ),
            create_table_from_model(CheckpointRow, table_name=CHECKPOINTS_TABLE),
            create_table_from_model(ArtifactRow, table_name=ARTIFACTS_TABLE),
            create_table_from_model(TaskRow, table_name=TASKS_TABLE),
            _with_uniques(
                ServiceDepRow,
                SESSION_SERVICES_TABLE,
                unique=["session_id", "service"],
                unique_name="uq_session_services",
            ),
            create_table_from_model(SuggestionRow, table_name=SUGGESTIONS_TABLE),
            create_table_from_model(DecisionRow, table_name=DECISIONS_TABLE),
        ]
    )


# Colunas aditivas da sessão project-scoped (ADR-017 Fatia A2). Tenants NOVOS já as
# recebem via CREATE TABLE (o SessionRow as declara); em tenants EXISTENTES o
# CREATE TABLE IF NOT EXISTS não altera nada, então fazemos um backfill idempotente
# (o erro de coluna duplicada é esperado e ignorado — não há downgrade destrutivo).
_SESSION_ADDED_COLUMNS: list[ColumnDef] = [
    ColumnDef(name="project_id", py_type=str, max_length=64, nullable=True),
    ColumnDef(name="agent_client", py_type=str, max_length=128, nullable=True),
    ColumnDef(name="environment_json", raw_type="TEXT", nullable=True),
]


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 7 tabelas no banco do tenant (idempotente `IF NOT EXISTS`) e faz o
    backfill aditivo das colunas project-scoped.

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)
    backfill = MigrationScript(
        up=[
            AddColumn(table=SESSIONS_TABLE, column=col, if_not_exists=True)
            for col in _SESSION_ADDED_COLUMNS
        ]
    )
    for statement in emit_ddl(backfill, engine):
        try:
            await pool.execute(statement)
        except Exception as exc:  # coluna já existe (MySQL omite IF NOT EXISTS) — idempotente
            _log.debug("session column backfill skipped: %s (%s)", statement, exc)


__all__ = [
    "SESSIONS_TABLE",
    "CHECKPOINTS_TABLE",
    "ARTIFACTS_TABLE",
    "TASKS_TABLE",
    "SESSION_SERVICES_TABLE",
    "SUGGESTIONS_TABLE",
    "DECISIONS_TABLE",
    "build_migration",
    "ensure_schema",
]
