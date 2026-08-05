# Portado de `services-mcp-server/tests/test_schema.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""DDL IR canônico (hermético): a migração da tabela `services` compila para MySQL e
PostgreSQL (dual-db), idempotente e com a UNIQUE de chave natural (`name`)."""

from __future__ import annotations

import pytest
from platform_database.orm.ddl import emit_ddl

from src.domains.services.db.schema import SERVICES_TABLE, build_migration


def _joined(engine: str) -> tuple[list[str], str]:
    statements = list(emit_ddl(build_migration(), engine))
    return statements, "\n".join(statements)


def test_services_table_name():
    assert SERVICES_TABLE == "services"


@pytest.mark.parametrize("engine", ["mysql", "postgresql"])
def test_migration_creates_services_table(engine):
    statements, sql = _joined(engine)
    assert len(statements) == 1  # uma CREATE TABLE
    assert SERVICES_TABLE in sql
    assert sql.count("CREATE TABLE") == 1
    assert "IF NOT EXISTS" in sql


@pytest.mark.parametrize("engine", ["mysql", "postgresql"])
def test_natural_key_unique_present(engine):
    _statements, sql = _joined(engine)
    assert "uq_services_name" in sql
    assert "name" in sql


def test_mysql_autoincrement_pk():
    _statements, sql = _joined("mysql")
    assert "AUTO_INCREMENT" in sql


def test_postgres_identity_pk():
    _statements, sql = _joined("postgresql")
    assert "IDENTITY" in sql
