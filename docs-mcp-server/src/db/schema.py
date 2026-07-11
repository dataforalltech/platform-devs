"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma) e — quando há chave natural — ganha a **constraint UNIQUE** como
constraint de tabela, renderizada DENTRO do `CREATE TABLE IF NOT EXISTS`, portanto
idempotente (criada só junto com a tabela, sem `CREATE INDEX` separado que quebraria
no re-run).

O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL / ON CONFLICT no
PG) depende dessa UNIQUE existir — é o que torna o índice de docs upsertable por
(repo_path, file_path), substituindo o update-then-insert RACY do store legado (que
não tinha unique nenhuma no banco).

NOTA: o repo legado não tinha DDL algum (a tabela `documents` era provisionada
externamente); este módulo PREENCHE esse gap — as duas tabelas são criadas pelo
próprio serviço, por tenant.

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

from ..models import AuditRow, DocIndexRow

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
AUDITS_TABLE = "audits"
DOC_INDEX_TABLE = "doc_index"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 2 tabelas do docs-mcp (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(AuditRow, table_name=AUDITS_TABLE),
            _with_uniques(
                DocIndexRow,
                DOC_INDEX_TABLE,
                unique=["repo_path", "file_path"],
                unique_name="uq_doc_index_repo_file",
            ),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 2 tabelas no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "AUDITS_TABLE",
    "DOC_INDEX_TABLE",
    "build_migration",
    "ensure_schema",
]
