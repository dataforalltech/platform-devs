"""Add the first-class external_link column to repository bindings (ADR-017 D17.6).

Revision ID: 0003_binding_external_link
Revises: 0002_integrity_idempotency
Create Date: 2026-07-21
"""

from __future__ import annotations

from sqlalchemy import inspect

from alembic import op

revision = "0003_binding_external_link"
down_revision = "0002_integrity_idempotency"
branch_labels = None
depends_on = None

_LOCK_NAME = "platform-project-product:0003"
_TABLE = "portfolio_project_repository_bindings"


def _engine_name() -> str:
    name = str(op.get_bind().dialect.name).lower()
    if name not in {"postgresql", "mysql"}:
        raise RuntimeError(f"Unsupported project-product migration engine: {name!r}")
    return name


def _physical_table(engine: str) -> str:
    return _TABLE.upper() if engine == "mysql" else _TABLE.lower()


def _column_type(engine: str) -> str:
    return "JSON" if engine == "mysql" else "JSONB"


def _has_column(table: str, column: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(
        str(item.get("name", "")).casefold() == column.casefold()
        for item in inspector.get_columns(table)
    )


def _acquire_lock(engine: str) -> None:
    if engine == "postgresql":
        op.execute(f"SELECT pg_advisory_xact_lock(hashtext('{_LOCK_NAME}'))")
        return
    acquired = (
        op.get_bind().exec_driver_sql("SELECT GET_LOCK(%s, %s)", (_LOCK_NAME, 60)).scalar_one()
    )
    if acquired != 1:
        raise RuntimeError("Could not acquire project-product MySQL migration lock")


def _release_lock(engine: str) -> None:
    if engine == "mysql":
        op.get_bind().exec_driver_sql("SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,))


def upgrade() -> None:
    engine = _engine_name()
    _acquire_lock(engine)
    try:
        table = _physical_table(engine)
        if not _has_column(table, "external_link"):
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN external_link {_column_type(engine)} NULL"
            )
    finally:
        _release_lock(engine)


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only migration: destructive downgrade requires an approved rollback migration"
    )
