"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma) e ganha as **constraints UNIQUE de chave natural** como constraints de
tabela — renderizadas DENTRO do `CREATE TABLE IF NOT EXISTS`, portanto idempotentes
(criadas só junto com a tabela, sem `CREATE INDEX` separado que quebraria no re-run).

O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL) depende dessas
UNIQUE existirem — é o que torna a auditoria upsertable por (``audit_key``) e a
criticidade por (``service``). As tabelas-filhas (``audit_items``/``audit_approvals``)
são append-only (INSERT puro) e não precisam de UNIQUE.

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

from ..models.entities import (
    AuditApprovalRow,
    AuditItemRow,
    AuditRow,
    ServiceCriticalityRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
AUDITS_TABLE = "audits"
AUDIT_ITEMS_TABLE = "audit_items"
AUDIT_APPROVALS_TABLE = "audit_approvals"
SERVICE_CRITICALITY_TABLE = "service_criticality"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 4 tabelas do audit (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_uniques(
                AuditRow,
                AUDITS_TABLE,
                unique=["audit_key"],
                unique_name="uq_audits_key",
            ),
            create_table_from_model(AuditItemRow, table_name=AUDIT_ITEMS_TABLE),
            create_table_from_model(AuditApprovalRow, table_name=AUDIT_APPROVALS_TABLE),
            _with_uniques(
                ServiceCriticalityRow,
                SERVICE_CRITICALITY_TABLE,
                unique=["service"],
                unique_name="uq_service_criticality_service",
            ),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 4 tabelas no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "AUDITS_TABLE",
    "AUDIT_ITEMS_TABLE",
    "AUDIT_APPROVALS_TABLE",
    "SERVICE_CRITICALITY_TABLE",
    "build_migration",
    "ensure_schema",
]
