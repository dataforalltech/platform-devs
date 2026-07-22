"""Bootstrap de schema por-tenant do domínio `guardian` (ADR-018 Fase 1 + 1c).

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
    GovDirectiveRow,
    GovDirectiveVersionRow,
    GovKindCapabilityRow,
    GovLcrDetailRow,
    GovLcrSubstitutionRow,
    GovStatusVocabRow,
)

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
KIND_CAPABILITY_TABLE = "gov_kind_capability"
STATUS_VOCAB_TABLE = "gov_status_vocab"
DIRECTIVE_TABLE = "gov_directive"
DIRECTIVE_VERSION_TABLE = "gov_directive_version"
LCR_DETAIL_TABLE = "gov_lcr_detail"
LCR_SUBSTITUTION_TABLE = "gov_lcr_substitution"


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
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as tabelas do guardian no banco do tenant (idempotente `IF NOT EXISTS`)."""
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "KIND_CAPABILITY_TABLE",
    "STATUS_VOCAB_TABLE",
    "DIRECTIVE_TABLE",
    "DIRECTIVE_VERSION_TABLE",
    "build_migration",
    "ensure_schema",
]
