"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). A tabela de sugestões ganha a **constraint UNIQUE de chave natural**
(``suggestion_id``) como constraint de tabela — renderizada DENTRO do
`CREATE TABLE IF NOT EXISTS`, portanto idempotente (sem `CREATE INDEX` separado que
quebraria no re-run). A trilha de auditoria é append-only (só a chave surrogate
``id``), sem UNIQUE.

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

from .models import DecisionAuditRow, SuggestionRow

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
SUGGESTIONS_TABLE = "governance_suggestions"
AUDIT_TABLE = "governance_decision_audit"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 2 tabelas mutáveis do ai-governance (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_uniques(
                SuggestionRow,
                SUGGESTIONS_TABLE,
                unique=["suggestion_id"],
                unique_name="uq_governance_suggestions_sid",
            ),
            create_table_from_model(DecisionAuditRow, table_name=AUDIT_TABLE),
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
    "SUGGESTIONS_TABLE",
    "AUDIT_TABLE",
    "build_migration",
    "ensure_schema",
]
