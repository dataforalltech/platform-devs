"""Add durable idempotency and enforce real table-level foreign keys.

Revision ID: 0002_integrity_idempotency
Revises: 0001_project_product
Create Date: 2026-07-20
"""

from __future__ import annotations

from uuid import UUID

from platform_database.orm.ddl import (
    CheckConstraint,
    ColumnDef,
    CreateIndex,
    CreateTable,
    MigrationScript,
    UniqueConstraintSpec,
    emit_ddl,
)
from sqlalchemy import inspect

from alembic import op

revision = "0002_integrity_idempotency"
down_revision = "0001_project_product"
branch_labels = None
depends_on = None

_LOCK_NAME = "platform-project-product:0002"
_IDEMPOTENCY = "PORTFOLIO_IDEMPOTENCY_KEYS"


def _engine_name() -> str:
    name = str(op.get_bind().dialect.name).lower()
    if name not in {"postgresql", "mysql"}:
        raise RuntimeError(f"Unsupported project-product migration engine: {name!r}")
    return name


def _timestamp_type(engine: str) -> str:
    return "DATETIME(6)" if engine == "mysql" else "TIMESTAMPTZ"


def _timestamp_default(engine: str) -> str:
    return "CURRENT_TIMESTAMP(6)" if engine == "mysql" else "CURRENT_TIMESTAMP"


def _idempotency_table(engine: str) -> CreateTable:
    timestamp_type = _timestamp_type(engine)
    timestamp_default = _timestamp_default(engine)
    return CreateTable(
        table=_IDEMPOTENCY,
        columns=[
            ColumnDef(
                name="id",
                py_type=int,
                nullable=False,
                primary_key=True,
                autoincrement=True,
                big=True,
            ),
            ColumnDef(name="id_environment", raw_type="SMALLINT", nullable=False),
            ColumnDef(name="id_owner", py_type=int, big=True, nullable=False),
            ColumnDef(
                name="idempotency_key",
                raw_type_by_engine={
                    "postgresql": "VARCHAR(128)",
                    "mysql": "VARCHAR(128) COLLATE utf8mb4_bin",
                },
                nullable=False,
            ),
            ColumnDef(name="operation", py_type=str, max_length=64, nullable=False),
            ColumnDef(
                name="request_hash",
                raw_type_by_engine={
                    "postgresql": "CHAR(64)",
                    "mysql": "CHAR(64) COLLATE utf8mb4_bin",
                },
                nullable=False,
            ),
            ColumnDef(name="target_type", py_type=str, max_length=32, nullable=False),
            ColumnDef(name="target_id", py_type=UUID, nullable=False),
            ColumnDef(name="response_body", py_type=dict, nullable=False),
            ColumnDef(name="status", py_type=str, max_length=16, nullable=False),
            ColumnDef(name="is_active", py_type=bool, nullable=False, default_sql="TRUE"),
            ColumnDef(name="is_deleted", py_type=bool, nullable=False, default_sql="FALSE"),
            ColumnDef(
                name="created_at",
                raw_type=timestamp_type,
                nullable=False,
                default_sql=timestamp_default,
            ),
            ColumnDef(
                name="updated_at",
                raw_type=timestamp_type,
                nullable=False,
                default_sql=timestamp_default,
            ),
            ColumnDef(name="created_by", py_type=int, big=True, nullable=False),
            ColumnDef(name="updated_by", py_type=int, big=True, nullable=False),
            ColumnDef(name="active", raw_type="SMALLINT", nullable=False, default_sql="1"),
            ColumnDef(name="excluded", raw_type="SMALLINT", nullable=False, default_sql="0"),
            ColumnDef(
                name="create_on",
                raw_type=timestamp_type,
                nullable=False,
                default_sql=timestamp_default,
            ),
            ColumnDef(
                name="timestamp_refresh",
                raw_type=timestamp_type,
                nullable=False,
                default_sql=timestamp_default,
            ),
            ColumnDef(name="id_user_created", py_type=int, big=True, nullable=False),
            ColumnDef(name="id_user_modify", py_type=int, big=True),
            ColumnDef(
                name="scope",
                py_type=str,
                max_length=64,
                default_sql="'portfolio_idempotency_keys'",
            ),
        ],
        checks=[
            CheckConstraint(
                name="ck_portfolio_idempotency_scope",
                expression="id_environment >= 0 AND id_owner >= 0",
            ),
            CheckConstraint(
                name="ck_portfolio_idempotency_status",
                expression="status IN ('pending','completed')",
            ),
        ],
        uniques=[
            UniqueConstraintSpec(
                name="uq_portfolio_idempotency_key",
                columns=["id_environment", "id_owner", "idempotency_key"],
            )
        ],
    )


def build_upgrade_statements(engine: str) -> list[str]:
    normalized = str(engine).lower()
    if normalized not in {"postgresql", "mysql"}:
        raise ValueError(f"Unsupported project-product migration engine: {engine!r}")
    script = MigrationScript(
        up=[
            _idempotency_table(normalized),
            CreateIndex(
                table=_IDEMPOTENCY,
                name="ix_portfolio_idempotency_target",
                columns=["id_environment", "id_owner", "target_type", "target_id"],
            ),
        ]
    )
    return emit_ddl(script, normalized)


def _physical_table(engine: str, name: str) -> str:
    return name.upper() if engine == "mysql" else name.lower()


def _has_foreign_key(
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
) -> bool:
    inspector = inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(source_table):
        constrained = [str(item).casefold() for item in foreign_key.get("constrained_columns", [])]
        referred = [str(item).casefold() for item in foreign_key.get("referred_columns", [])]
        referred_table = str(foreign_key.get("referred_table") or "").casefold()
        if (
            constrained == [source_column.casefold()]
            and referred == [target_column.casefold()]
            and referred_table == target_table.casefold()
        ):
            return True
    return False


def _ensure_foreign_keys(engine: str) -> None:
    products = _physical_table(engine, "portfolio_products")
    projects = _physical_table(engine, "portfolio_projects")
    bindings = _physical_table(engine, "portfolio_project_repository_bindings")
    if not _has_foreign_key(projects, "product_id", products, "product_id"):
        op.create_foreign_key(
            "fk_portfolio_projects_product",
            projects,
            products,
            ["product_id"],
            ["product_id"],
            ondelete="RESTRICT",
        )
    if not _has_foreign_key(bindings, "project_id", projects, "project_id"):
        op.create_foreign_key(
            "fk_portfolio_bindings_project",
            bindings,
            projects,
            ["project_id"],
            ["project_id"],
            ondelete="RESTRICT",
        )


def _acquire_lock(engine: str) -> None:
    if engine == "postgresql":
        op.execute(f"SELECT pg_advisory_xact_lock(hashtext('{_LOCK_NAME}'))")
        return
    acquired = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT GET_LOCK(%s, %s)",
            (_LOCK_NAME, 60),
        )
        .scalar_one()
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
        for statement in build_upgrade_statements(engine):
            op.execute(statement)
        _ensure_foreign_keys(engine)
    finally:
        _release_lock(engine)


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only migration: destructive downgrade requires an approved rollback migration"
    )
