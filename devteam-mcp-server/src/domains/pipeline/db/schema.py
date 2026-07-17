"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma) e ganha as **constraints UNIQUE de chave natural** como constraints de
tabela — renderizadas DENTRO do `CREATE TABLE IF NOT EXISTS`, portanto idempotentes
(criadas só junto com a tabela, sem `CREATE INDEX` separado que quebraria no re-run).

O `upsert` do Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL) depende dessas
UNIQUE existirem — é o que torna o gate upsertable por (service, env, gate_type) e o
pipeline por (service).

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

from ..models import GateRow, PipelineRow, PromotionRow

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
PIPELINES_TABLE = "pipelines"
PROMOTIONS_TABLE = "promotions"
GATES_TABLE = "gates"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 3 tabelas do pipeline (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_uniques(
                PipelineRow,
                PIPELINES_TABLE,
                unique=["service"],
                unique_name="uq_pipelines_service",
            ),
            create_table_from_model(PromotionRow, table_name=PROMOTIONS_TABLE),
            _with_uniques(
                GateRow,
                GATES_TABLE,
                unique=["service", "env", "gate_type"],
                unique_name="uq_gates_svc_env_type",
            ),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 3 tabelas no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "PIPELINES_TABLE",
    "PROMOTIONS_TABLE",
    "GATES_TABLE",
    "build_migration",
    "ensure_schema",
]
