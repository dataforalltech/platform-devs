"""Create the canonical project/product portfolio schema.

Revision ID: 0001_project_product
Revises:
Create Date: 2026-07-19
"""

from __future__ import annotations

from uuid import UUID

from platform_database.orm.ddl import (
    CheckConstraint,
    ColumnDef,
    CreateIndex,
    CreateTable,
    ForeignKeySpec,
    MigrationScript,
    UniqueConstraintSpec,
    emit_ddl,
)

from alembic import op

revision = "0001_project_product"
down_revision = None
branch_labels = None
depends_on = None

_LOCK_NAME = "platform-project-product:0001"
_PRODUCTS = "PORTFOLIO_PRODUCTS"
_PROJECTS = "PORTFOLIO_PROJECTS"
_BINDINGS = "PORTFOLIO_PROJECT_REPOSITORY_BINDINGS"


def _engine_name() -> str:
    name = str(op.get_bind().dialect.name).lower()
    if name not in {"postgresql", "mysql"}:
        raise RuntimeError(f"Unsupported project-product migration engine: {name!r}")
    return name


def _base_columns(scope: str, engine: str) -> list[ColumnDef]:
    timestamp_type = {"postgresql": "TIMESTAMPTZ", "mysql": "DATETIME(6)"}
    timestamp_default = "CURRENT_TIMESTAMP(6)" if engine == "mysql" else "CURRENT_TIMESTAMP"
    return [
        ColumnDef(
            name="id",
            py_type=int,
            nullable=False,
            primary_key=True,
            autoincrement=True,
            big=True,
        ),
        ColumnDef(
            name="version",
            py_type=int,
            nullable=False,
            default_sql="1",
            check="version > 0",
        ),
        ColumnDef(
            name="last_idempotency_key",
            raw_type_by_engine={
                "postgresql": "VARCHAR(128)",
                "mysql": "VARCHAR(128) COLLATE utf8mb4_bin",
            },
            nullable=False,
        ),
        ColumnDef(
            name="id_environment",
            raw_type="SMALLINT",
            nullable=False,
            check="id_environment >= 0",
        ),
        ColumnDef(name="id_owner", py_type=int, big=True, nullable=False, check="id_owner >= 0"),
        ColumnDef(name="is_active", py_type=bool, nullable=False, default_sql="TRUE"),
        ColumnDef(name="is_deleted", py_type=bool, nullable=False, default_sql="FALSE"),
        ColumnDef(
            name="created_at",
            raw_type_by_engine=timestamp_type,
            nullable=False,
            default_sql=timestamp_default,
        ),
        ColumnDef(
            name="updated_at",
            raw_type_by_engine=timestamp_type,
            nullable=False,
            default_sql=timestamp_default,
        ),
        ColumnDef(name="deleted_at", raw_type_by_engine=timestamp_type),
        ColumnDef(name="created_by", py_type=int, big=True, nullable=False),
        ColumnDef(name="updated_by", py_type=int, big=True, nullable=False),
        ColumnDef(name="deleted_by", py_type=int, big=True),
        ColumnDef(name="active", raw_type="SMALLINT", nullable=False, default_sql="1"),
        ColumnDef(name="excluded", raw_type="SMALLINT", nullable=False, default_sql="0"),
        ColumnDef(
            name="create_on",
            raw_type_by_engine=timestamp_type,
            nullable=False,
            default_sql=timestamp_default,
        ),
        ColumnDef(
            name="timestamp_refresh",
            raw_type_by_engine=timestamp_type,
            nullable=False,
            default_sql=timestamp_default,
        ),
        ColumnDef(name="id_user_created", py_type=int, big=True, nullable=False),
        ColumnDef(name="id_user_modify", py_type=int, big=True),
        ColumnDef(
            name="scope",
            py_type=str,
            max_length=64,
            default_sql=f"'{scope}'",
        ),
    ]


def _mysql_live_column(name: str, expression: str, sql_type: str) -> ColumnDef:
    return ColumnDef(
        name=name,
        raw_type=f"{sql_type} GENERATED ALWAYS AS ({expression}) STORED",
    )


def _product_table(engine: str) -> CreateTable:
    columns = [
        *_base_columns("portfolio_products", engine),
        ColumnDef(name="product_id", py_type=UUID, nullable=False, unique=True),
        ColumnDef(name="slug", py_type=str, max_length=80, nullable=False),
        ColumnDef(name="name", py_type=str, max_length=200, nullable=False),
        ColumnDef(name="description", py_type=str, max_length=4000),
        ColumnDef(name="status", py_type=str, max_length=16, nullable=False),
        ColumnDef(name="owner_user_refs", py_type=list, nullable=False),
    ]
    uniques = [
        UniqueConstraintSpec(
            name="uq_portfolio_products_idempotency",
            columns=["id_environment", "id_owner", "last_idempotency_key"],
        )
    ]
    if engine == "mysql":
        columns.append(
            _mysql_live_column(
                "live_slug",
                "CASE WHEN is_deleted = 0 THEN slug ELSE NULL END",
                "VARCHAR(80)",
            )
        )
        uniques.append(
            UniqueConstraintSpec(
                name="uq_portfolio_products_live_slug",
                columns=["id_environment", "id_owner", "live_slug"],
            )
        )
    return CreateTable(
        table=_PRODUCTS,
        columns=columns,
        checks=[
            CheckConstraint(
                name="ck_portfolio_products_status",
                expression="status IN ('planned','active','paused','retired')",
            )
        ],
        uniques=uniques,
    )


def _project_table(engine: str) -> CreateTable:
    columns = [
        *_base_columns("portfolio_projects", engine),
        ColumnDef(name="project_id", py_type=UUID, nullable=False, unique=True),
        ColumnDef(
            name="product_id",
            py_type=UUID,
            nullable=False,
        ),
        ColumnDef(name="slug", py_type=str, max_length=80, nullable=False),
        ColumnDef(name="name", py_type=str, max_length=200, nullable=False),
        ColumnDef(name="description", py_type=str, max_length=4000),
        ColumnDef(name="status", py_type=str, max_length=16, nullable=False),
        ColumnDef(name="owner_user_refs", py_type=list, nullable=False),
        ColumnDef(name="service_refs", py_type=dict, nullable=False),
    ]
    uniques = [
        UniqueConstraintSpec(
            name="uq_portfolio_projects_idempotency",
            columns=["id_environment", "id_owner", "last_idempotency_key"],
        )
    ]
    if engine == "mysql":
        columns.append(
            _mysql_live_column(
                "live_slug",
                "CASE WHEN is_deleted = 0 THEN slug ELSE NULL END",
                "VARCHAR(80)",
            )
        )
        uniques.append(
            UniqueConstraintSpec(
                name="uq_portfolio_projects_live_slug",
                columns=["id_environment", "id_owner", "product_id", "live_slug"],
            )
        )
    return CreateTable(
        table=_PROJECTS,
        columns=columns,
        checks=[
            CheckConstraint(
                name="ck_portfolio_projects_status",
                expression="status IN ('planned','active','paused','completed','archived')",
            )
        ],
        uniques=uniques,
        foreign_keys=[
            ForeignKeySpec(
                name="fk_portfolio_projects_product",
                columns=["product_id"],
                ref_table=_PRODUCTS,
                ref_columns=["product_id"],
                on_delete="RESTRICT",
            )
        ],
    )


def _binding_table(engine: str) -> CreateTable:
    columns = [
        *_base_columns("portfolio_project_repository_bindings", engine),
        ColumnDef(name="binding_id", py_type=UUID, nullable=False, unique=True),
        ColumnDef(
            name="project_id",
            py_type=UUID,
            nullable=False,
        ),
        ColumnDef(name="provider", py_type=str, max_length=64, nullable=False),
        ColumnDef(
            name="connector_ref",
            raw_type_by_engine={
                "postgresql": "VARCHAR(512)",
                "mysql": "VARCHAR(512) COLLATE utf8mb4_bin",
            },
            nullable=False,
        ),
        ColumnDef(
            name="repository_ref",
            raw_type_by_engine={
                "postgresql": "VARCHAR(512)",
                "mysql": "VARCHAR(512) COLLATE utf8mb4_bin",
            },
            nullable=False,
        ),
        ColumnDef(name="role", py_type=str, max_length=32, nullable=False),
        ColumnDef(name="metadata", py_type=dict, nullable=False),
    ]
    uniques = [
        UniqueConstraintSpec(
            name="uq_portfolio_bindings_idempotency",
            columns=["id_environment", "id_owner", "last_idempotency_key"],
        )
    ]
    if engine == "mysql":
        columns.append(
            _mysql_live_column(
                "live_repository_key",
                (
                    "CASE WHEN is_deleted = 0 THEN "
                    "UNHEX(SHA2(CAST(JSON_ARRAY(provider, connector_ref, repository_ref, role) "
                    "AS CHAR), 256)) ELSE NULL END"
                ),
                "BINARY(32)",
            )
        )
        uniques.append(
            UniqueConstraintSpec(
                name="uq_portfolio_bindings_live_repository",
                columns=[
                    "id_environment",
                    "id_owner",
                    "project_id",
                    "live_repository_key",
                ],
            )
        )
    return CreateTable(
        table=_BINDINGS,
        columns=columns,
        checks=[
            CheckConstraint(
                name="ck_portfolio_bindings_role",
                expression=(
                    "role IN ('source','documentation','infrastructure','deployment','other')"
                ),
            )
        ],
        uniques=uniques,
        foreign_keys=[
            ForeignKeySpec(
                name="fk_portfolio_bindings_project",
                columns=["project_id"],
                ref_table=_PROJECTS,
                ref_columns=["project_id"],
                on_delete="RESTRICT",
            )
        ],
    )


def build_upgrade_statements(engine: str) -> list[str]:
    """Compile the same typed schema contract for a supported tenant engine."""
    normalized = str(engine).lower()
    if normalized not in {"postgresql", "mysql"}:
        raise ValueError(f"Unsupported project-product migration engine: {engine!r}")

    operations = [
        _product_table(normalized),
        _project_table(normalized),
        _binding_table(normalized),
    ]
    if normalized == "postgresql":
        operations.extend(
            [
                CreateIndex(
                    table=_PRODUCTS,
                    name="uq_portfolio_products_live_slug",
                    columns=["id_environment", "id_owner", "slug"],
                    unique=True,
                    where="is_deleted = FALSE",
                ),
                CreateIndex(
                    table=_PRODUCTS,
                    name="ix_portfolio_products_scope",
                    columns=["id_environment", "id_owner", "product_id"],
                    where="is_deleted = FALSE",
                ),
                CreateIndex(
                    table=_PROJECTS,
                    name="uq_portfolio_projects_live_slug",
                    columns=["id_environment", "id_owner", "product_id", "slug"],
                    unique=True,
                    where="is_deleted = FALSE",
                ),
                CreateIndex(
                    table=_PROJECTS,
                    name="ix_portfolio_projects_scope",
                    columns=["id_environment", "id_owner", "project_id"],
                    where="is_deleted = FALSE",
                ),
                CreateIndex(
                    table=_BINDINGS,
                    name="uq_portfolio_bindings_live_repository",
                    columns=[
                        "id_environment",
                        "id_owner",
                        "project_id",
                        "provider",
                        "connector_ref",
                        "repository_ref",
                        "role",
                    ],
                    unique=True,
                    where="is_deleted = FALSE",
                ),
                CreateIndex(
                    table=_BINDINGS,
                    name="ix_portfolio_bindings_scope",
                    columns=["id_environment", "id_owner", "project_id", "binding_id"],
                    where="is_deleted = FALSE",
                ),
            ]
        )
    return emit_ddl(MigrationScript(up=operations), normalized)


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
        op.get_bind().exec_driver_sql(
            "SELECT RELEASE_LOCK(%s)",
            (_LOCK_NAME,),
        )


def upgrade() -> None:
    engine = _engine_name()
    _acquire_lock(engine)
    try:
        for statement in build_upgrade_statements(engine):
            op.execute(statement)
    finally:
        _release_lock(engine)


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only migration: destructive downgrade requires an approved rollback migration"
    )
