"""Bootstrap de schema por-tenant do domínio `guardian` (ADR-018 Fase 1 + 1c + 2).

Cada tabela é um `CreateTable` derivado do modelo Pydantic (`create_table_from_model`,
injeta as colunas-padrão da plataforma). As tabelas com **chave natural** ganham uma
constraint UNIQUE de tabela (renderizada DENTRO do `CREATE TABLE IF NOT EXISTS`,
idempotente) — o `upsert` do Repository depende dela. Idempotente e dual-engine via
`emit_ddl(script, engine)`.

Fase 1: `gov_directive` (uid único) + `gov_directive_version` (uid+version único) —
o núcleo versionado; `gov_kind_capability` (kind único) + `gov_status_vocab` (code único)
— dados de referência (semeados por `store.seed_reference_data`). CHECK/FK entre tabelas
são enforce-ados app-level nesta fase (D18: matriz honesta) — o wiring de CHECK/FK no DDL
IR fica p/ refinamento.

Fase 1c: `gov_lcr_detail` (directive_uid único) — metadados de gestão de mudança de
Library Change Request, sem equivalente no núcleo versionado; `gov_lcr_substitution`
(directive_uid+target_ref único) — a aresta `substituido_por` do LCR (lista no
front-matter) normalizada em linhas, não serializada (D18.2: rejeição de JSON-blob).

Fase 2: `gov_directive_section` (directive_uid+version+order_index único) — corpo
tipado por heading; `gov_directive_relation` (from_uid+to_ref+relation_type único) —
arestas `governado_por`/matriz de rastreabilidade. `gov_directive` ganha a coluna
`archetype_ref` (backfill idempotente para tenants já provisionados na Fase 1 — o
`CREATE TABLE IF NOT EXISTS` não altera tabelas existentes, mesmo padrão do domínio
`session`, ADR-017 Fatia A2).
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
    GovDirectiveRelationRow,
    GovDirectiveRow,
    GovDirectiveSectionRow,
    GovDirectiveVersionRow,
    GovKindCapabilityRow,
    GovLcrDetailRow,
    GovLcrSubstitutionRow,
    GovStatusVocabRow,
)

_log = logging.getLogger(__name__)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
KIND_CAPABILITY_TABLE = "gov_kind_capability"
STATUS_VOCAB_TABLE = "gov_status_vocab"
DIRECTIVE_TABLE = "gov_directive"
DIRECTIVE_VERSION_TABLE = "gov_directive_version"
LCR_DETAIL_TABLE = "gov_lcr_detail"
LCR_SUBSTITUTION_TABLE = "gov_lcr_substitution"
DIRECTIVE_SECTION_TABLE = "gov_directive_section"
DIRECTIVE_RELATION_TABLE = "gov_directive_relation"

# Coluna aditiva do escopo archetype (Fase 2) — ver docstring do módulo.
_DIRECTIVE_ADDED_COLUMNS: list[ColumnDef] = [
    ColumnDef(name="archetype_ref", py_type=str, max_length=64, nullable=True),
]


def _with_uniques(
    model: type, table_name: str, *, unique: list[str], unique_name: str
) -> CreateTable:
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(
        update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]}
    )


def build_migration() -> MigrationScript:
    """Criação das 4 tabelas do núcleo do guardian (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_uniques(
                GovKindCapabilityRow,
                KIND_CAPABILITY_TABLE,
                unique=["kind"],
                unique_name="uq_gov_kind_capability_kind",
            ),
            _with_uniques(
                GovStatusVocabRow,
                STATUS_VOCAB_TABLE,
                unique=["code"],
                unique_name="uq_gov_status_vocab_code",
            ),
            _with_uniques(
                GovDirectiveRow,
                DIRECTIVE_TABLE,
                unique=["directive_uid"],
                unique_name="uq_gov_directive_uid",
            ),
            _with_uniques(
                GovDirectiveVersionRow,
                DIRECTIVE_VERSION_TABLE,
                unique=["directive_uid", "version"],
                unique_name="uq_gov_directive_version",
            ),
            _with_uniques(
                GovLcrDetailRow,
                LCR_DETAIL_TABLE,
                unique=["directive_uid"],
                unique_name="uq_gov_lcr_detail_uid",
            ),
            _with_uniques(
                GovLcrSubstitutionRow,
                LCR_SUBSTITUTION_TABLE,
                unique=["lcr_directive_uid", "target_ref"],
                unique_name="uq_gov_lcr_substitution",
            ),
            _with_uniques(
                GovDirectiveSectionRow,
                DIRECTIVE_SECTION_TABLE,
                unique=["directive_uid", "version", "order_index"],
                unique_name="uq_gov_directive_section",
            ),
            _with_uniques(
                GovDirectiveRelationRow,
                DIRECTIVE_RELATION_TABLE,
                unique=["from_uid", "to_ref", "relation_type"],
                unique_name="uq_gov_directive_relation",
            ),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as tabelas do guardian no banco do tenant (idempotente `IF NOT EXISTS`)
    e faz o backfill aditivo de `archetype_ref` (Fase 2) em tenants já provisionados
    na Fase 1 — `CREATE TABLE IF NOT EXISTS` não altera uma tabela existente."""
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)
    backfill = MigrationScript(
        up=[
            AddColumn(table=DIRECTIVE_TABLE, column=col, if_not_exists=True)
            for col in _DIRECTIVE_ADDED_COLUMNS
        ]
    )
    for statement in emit_ddl(backfill, engine):
        try:
            await pool.execute(statement)
        except (
            Exception
        ) as exc:  # coluna já existe (MySQL omite IF NOT EXISTS) — idempotente
            _log.debug("guardian column backfill skipped: %s (%s)", statement, exc)


__all__ = [
    "KIND_CAPABILITY_TABLE",
    "STATUS_VOCAB_TABLE",
    "DIRECTIVE_TABLE",
    "DIRECTIVE_VERSION_TABLE",
    "LCR_DETAIL_TABLE",
    "LCR_SUBSTITUTION_TABLE",
    "DIRECTIVE_SECTION_TABLE",
    "DIRECTIVE_RELATION_TABLE",
    "build_migration",
    "ensure_schema",
]
