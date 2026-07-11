"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: a tabela é um `CreateTable` derivado do modelo
Pydantic (`create_table_from_model`, que injeta as colunas padrão da plataforma) e
ganha a **constraint UNIQUE de chave natural** como constraint de tabela — renderizada
DENTRO do `CREATE TABLE IF NOT EXISTS`, portanto idempotente (criada só junto com a
tabela, sem `CREATE INDEX` separado que quebraria no re-run).

O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL) depende dessa
UNIQUE existir — é o que torna a entrada upsertable por (namespace, config_key).

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

from ..models import ConfigEntryRow

# Nome físico da tabela (table-case "lower" por padrão — tenants novos).
CONFIG_ENTRIES_TABLE = "config_entries"


def _config_entries_table() -> CreateTable:
    """`CreateTable` do modelo + a UNIQUE de tabela sobre (namespace, config_key)."""
    ct = create_table_from_model(ConfigEntryRow, table_name=CONFIG_ENTRIES_TABLE)
    return ct.model_copy(
        update={
            "uniques": [
                UniqueConstraintSpec(
                    name="uq_config_ns_key",
                    columns=["namespace", "config_key"],
                )
            ]
        }
    )


def build_migration() -> MigrationScript:
    """A migração de criação da tabela de configuração (up-only, idempotente)."""
    return MigrationScript(up=[_config_entries_table()])


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria a tabela no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "CONFIG_ENTRIES_TABLE",
    "build_migration",
    "ensure_schema",
]
