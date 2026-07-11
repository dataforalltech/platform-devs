"""DDL IR canônico (hermético): a migração compila para MySQL e PostgreSQL (dual-db).

Sem tocar banco — só exercita `build_migration`/`emit_ddl`, garantindo que as 4
tabelas e as UNIQUE de chave natural saem no SQL de cada dialeto.
"""

from __future__ import annotations

import pytest

from src.db.schema import (
    AUDIT_APPROVALS_TABLE,
    AUDIT_ITEMS_TABLE,
    AUDITS_TABLE,
    SERVICE_CRITICALITY_TABLE,
    build_migration,
)

try:
    from platform_database.orm.ddl import emit_ddl

    _HAVE_DDL = True
except Exception:  # pragma: no cover - a lib está instalada no venv
    _HAVE_DDL = False

pytestmark = pytest.mark.skipif(not _HAVE_DDL, reason="platform_database.orm.ddl indisponível")


def _joined(engine: str) -> tuple[list[str], str]:
    statements = list(emit_ddl(build_migration(), engine))
    return statements, "\n".join(statements)


@pytest.mark.parametrize("engine", ["mysql", "postgresql"])
def test_migration_creates_all_four_tables(engine):
    statements, sql = _joined(engine)
    assert len(statements) == 4  # uma CREATE TABLE por tabela
    for table in (AUDITS_TABLE, AUDIT_ITEMS_TABLE, AUDIT_APPROVALS_TABLE, SERVICE_CRITICALITY_TABLE):
        assert table in sql
    # CREATE idempotente
    assert sql.count("CREATE TABLE") == 4
    assert "IF NOT EXISTS" in sql


@pytest.mark.parametrize("engine", ["mysql", "postgresql"])
def test_natural_key_uniques_present(engine):
    _statements, sql = _joined(engine)
    assert "uq_audits_key" in sql
    assert "uq_service_criticality_service" in sql
    assert "audit_key" in sql  # chave natural determinística


def test_mysql_autoincrement_pk():
    _statements, sql = _joined("mysql")
    assert "AUTO_INCREMENT" in sql


def test_postgres_identity_pk():
    _statements, sql = _joined("postgresql")
    assert "IDENTITY" in sql
