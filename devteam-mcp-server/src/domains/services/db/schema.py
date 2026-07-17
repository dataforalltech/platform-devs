"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: a tabela `services` é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da plataforma)
e ganha a **constraint UNIQUE de chave natural** (`name`) como constraint de tabela —
renderizada DENTRO do `CREATE TABLE IF NOT EXISTS`, portanto idempotente (criada só junto
com a tabela, sem `CREATE INDEX` separado que quebraria no re-run).

A chave natural `name` (VARCHAR(255)) é o que torna o registry consultável/atualizável
por serviço; o ORM injeta o surrogate `id` PK + auditoria + soft-delete `excluded`.

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

from ..models.service import ServiceRow

# Nome físico da tabela (table-case "lower" por padrão — tenants novos).
SERVICES_TABLE = "services"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação da tabela `services` (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_uniques(
                ServiceRow,
                SERVICES_TABLE,
                unique=["name"],
                unique_name="uq_services_name",
            ),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria a tabela `services` no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "SERVICES_TABLE",
    "build_migration",
    "ensure_schema",
]
