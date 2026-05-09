"""Testes da tool validate_migration.

Cada caso usa string Python literal representando um arquivo de migration
Alembic. Cobre cada uma das 5 verificações da §29 AGENTS.md.
"""

from __future__ import annotations

import pytest

from src.tools.migration_tool import validate_migration

# Migration "feliz" — usada como base para mutations negativas.
GOOD_MIGRATION = '''\
"""adicionar coluna email"""

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255)
        )
    """))


def downgrade():
    op.execute(sa.text("DROP TABLE IF EXISTS users"))
'''


# --------------------------- happy path --------------------------- #
def test_validate_migration_approves_good_migration(repo):
    res = validate_migration(repo, content=GOOD_MIGRATION)
    assert res["approved"] is True
    assert res["issues"] == []
    assert res["checks"]["no_orm_operations"] is True
    assert res["checks"]["uses_sa_text"] is True
    assert res["checks"]["uses_raw_sql"] is True
    assert res["checks"]["is_idempotent"] is True
    assert res["checks"]["no_data_destroying_drops"] is True
    assert res["checks"]["has_reversible_downgrade"] is True


def test_validate_migration_validates_input(repo):
    with pytest.raises(ValueError):
        validate_migration(repo, content="")


# --------------------------- check 1: ORM --------------------------- #
def test_blocks_session_orm_usage(repo):
    bad = '''\
def upgrade():
    session.add(User(name="foo"))
    session.commit()


def downgrade():
    pass
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False
    assert res["checks"]["no_orm_operations"] is False
    assert any("ORM" in i or "session" in i for i in res["issues"])


def test_blocks_models_import(repo):
    bad = '''\
from app.models import User


def upgrade():
    op.execute(sa.text("CREATE TABLE x (id INT)"))


def downgrade():
    op.execute(sa.text("DROP TABLE x"))
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False
    assert any("models" in i.lower() for i in res["issues"])


def test_blocks_metadata_create_all(repo):
    bad = '''\
from app.db import Base


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False
    assert res["checks"]["no_orm_operations"] is False


# --------------------------- check 2: sa.text vs raw string --------------------------- #
def test_warns_on_raw_string_execute(repo):
    """op.execute('CREATE TABLE...') sem sa.text — warning, não issue."""
    code = '''\
def upgrade():
    op.execute("CREATE TABLE IF NOT EXISTS x (id INT)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS x")
'''
    res = validate_migration(repo, content=code)
    # Sem sa.text é warning, não bloqueia (mas approves dependerá de outras checks)
    assert any("sa.text" in w for w in res["warnings"])
    assert res["checks"]["uses_sa_text"] is False


# --------------------------- check 3: idempotency --------------------------- #
def test_warns_on_create_table_without_if_not_exists(repo):
    code = '''\
def upgrade():
    op.execute(sa.text("CREATE TABLE x (id INT)"))


def downgrade():
    op.execute(sa.text("DROP TABLE IF EXISTS x"))
'''
    res = validate_migration(repo, content=code)
    assert any("IF NOT EXISTS" in w for w in res["warnings"])
    assert res["checks"]["is_idempotent"] is False


def test_warns_on_add_column_without_if_not_exists(repo):
    code = '''\
def upgrade():
    op.add_column("users", sa.Column("email", sa.String(255)))


def downgrade():
    op.drop_column("users", "email")
'''
    res = validate_migration(repo, content=code)
    # add_column dispara o check
    assert res["checks"]["is_idempotent"] is False


# --------------------------- check 4: destructive ops in upgrade --------------------------- #
def test_blocks_drop_table_in_upgrade(repo):
    bad = '''\
def upgrade():
    op.execute(sa.text("DROP TABLE old_users"))


def downgrade():
    op.execute(sa.text("CREATE TABLE old_users (id INT)"))
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False
    assert res["checks"]["no_data_destroying_drops"] is False
    assert any("DROP" in i.upper() for i in res["issues"])


def test_blocks_drop_column_in_upgrade(repo):
    bad = '''\
def upgrade():
    op.drop_column("users", "deprecated_field")


def downgrade():
    op.add_column("users", sa.Column("deprecated_field", sa.String))
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False
    assert res["checks"]["no_data_destroying_drops"] is False


def test_blocks_truncate_in_upgrade(repo):
    bad = '''\
def upgrade():
    op.execute(sa.text("TRUNCATE TABLE logs"))


def downgrade():
    pass
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False


def test_blocks_delete_from_in_upgrade(repo):
    bad = '''\
def upgrade():
    op.execute(sa.text("DELETE FROM users WHERE created_at < '2020-01-01'"))


def downgrade():
    pass
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False


def test_drop_in_downgrade_is_acceptable(repo):
    """DROP em downgrade() é normal — só é bloqueado em upgrade()."""
    code = '''\
def upgrade():
    op.execute(sa.text("CREATE TABLE IF NOT EXISTS x (id INT)"))


def downgrade():
    op.execute(sa.text("DROP TABLE IF EXISTS x"))
'''
    res = validate_migration(repo, content=code)
    assert res["approved"] is True
    assert res["checks"]["no_data_destroying_drops"] is True


# --------------------------- check 5: downgrade --------------------------- #
def test_warns_on_noop_downgrade(repo):
    code = '''\
def upgrade():
    op.execute(sa.text("CREATE TABLE IF NOT EXISTS x (id INT)"))


def downgrade():
    pass
'''
    res = validate_migration(repo, content=code)
    assert any("downgrade" in w.lower() and "no-op" in w.lower() for w in res["warnings"])
    assert res["checks"]["has_reversible_downgrade"] is False


def test_warns_on_ellipsis_downgrade(repo):
    code = '''\
def upgrade():
    op.execute(sa.text("CREATE TABLE IF NOT EXISTS x (id INT)"))


def downgrade():
    ...
'''
    res = validate_migration(repo, content=code)
    assert res["checks"]["has_reversible_downgrade"] is False


def test_blocks_missing_downgrade(repo):
    code = '''\
def upgrade():
    op.execute(sa.text("CREATE TABLE IF NOT EXISTS x (id INT)"))
'''
    res = validate_migration(repo, content=code)
    assert res["approved"] is False
    assert any("downgrade" in i.lower() and "ausente" in i.lower() for i in res["issues"])


# --------------------------- multiple issues --------------------------- #
def test_aggregates_multiple_issues(repo):
    bad = '''\
from app.models import User


def upgrade():
    session.query(User).delete()
    op.execute("DROP TABLE users")
'''
    res = validate_migration(repo, content=bad)
    assert res["approved"] is False
    assert len(res["issues"]) >= 2  # ORM + DROP + missing downgrade
