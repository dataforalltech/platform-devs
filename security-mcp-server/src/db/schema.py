"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: cada tabela é um `CreateTable` derivado do
modelo Pydantic (`create_table_from_model`, que injeta as colunas padrão da
plataforma). A única tabela com **chave natural** é `sec_security_controls` (um
controle por `control_key` por `system_name`) — ela ganha uma constraint UNIQUE de tabela
sobre `(system_name, control_key)`, renderizada DENTRO do `CREATE TABLE IF NOT EXISTS`
(idempotente, sem `CREATE INDEX` avulso que quebraria no re-run). O `upsert` do
Repository (INSERT ... ON DUPLICATE KEY UPDATE no MySQL / ON CONFLICT no PG) depende
dessa UNIQUE existir. Coluna `system_name` (não `system`, palavra reservada do MySQL 8)
porque o ORM canônico emite identificadores UNQUOTED.

As demais tabelas (threat_models/cvss_assessments/artifacts) são históricos com chave
surrogate `id` — múltiplas linhas por (system_name/target/...) são o histórico esperado,
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
    CvssAssessmentRow,
    SecurityArtifactRow,
    SecurityControlRow,
    ThreatModelRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
THREAT_MODELS_TABLE = "sec_threat_models"
SECURITY_CONTROLS_TABLE = "sec_security_controls"
CVSS_ASSESSMENTS_TABLE = "sec_cvss_assessments"
ARTIFACTS_TABLE = "sec_artifacts"


def _with_uniques(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """`CreateTable` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 4 tabelas do security (up-only, idempotente)."""
    return MigrationScript(
        up=[
            create_table_from_model(ThreatModelRow, table_name=THREAT_MODELS_TABLE),
            _with_uniques(
                SecurityControlRow,
                SECURITY_CONTROLS_TABLE,
                unique=["system_name", "control_key"],
                unique_name="uq_sec_controls_system_key",
            ),
            create_table_from_model(CvssAssessmentRow, table_name=CVSS_ASSESSMENTS_TABLE),
            create_table_from_model(SecurityArtifactRow, table_name=ARTIFACTS_TABLE),
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
    "THREAT_MODELS_TABLE",
    "SECURITY_CONTROLS_TABLE",
    "CVSS_ASSESSMENTS_TABLE",
    "ARTIFACTS_TABLE",
    "build_migration",
    "ensure_schema",
]
