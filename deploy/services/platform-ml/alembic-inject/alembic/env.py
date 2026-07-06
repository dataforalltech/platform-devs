"""Alembic environment — SQLAlchemy-native, multi-tenant aware.

Uses SQLAlchemy Engine directly (no raw DBAPI2). Compatible with Alembic 1.x.

Usage:
    alembic upgrade head                   # service schema
    alembic -x schema=tenant_42 upgrade head  # specific tenant schema
    alembic downgrade -1                   # roll back last revision
    alembic revision -m "add_table"        # create new revision file
    alembic history                        # show all revisions
    alembic current                        # show current DB revision
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings

# ---------------------------------------------------------------------------
# Alembic config
# ---------------------------------------------------------------------------

alembic_cfg = context.config

if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

# Pure SQL migrations (op.execute) — no ORM metadata needed.
target_metadata = None


# ---------------------------------------------------------------------------
# Schema resolution
# ---------------------------------------------------------------------------


def _get_dsn() -> str:
    """Resolve the target schema DSN.

    Priority:
    1. ``sqlalchemy.url`` set programmatically via Config.set_main_option
       (used by MigrationManager.migrate_for_tenant to target a specific tenant DB).
    2. ``-x schema=tenant_42`` CLI flag  → tenant schema (separate MySQL DB or PG search_path).
    3. Default                           → public / main schema via settings.
    """
    cfg_url = context.config.get_main_option("sqlalchemy.url")
    if cfg_url:
        return cfg_url
    schema = context.get_x_argument(as_dictionary=True).get("schema", "public")
    return settings.db_url_for_schema(schema)


# ---------------------------------------------------------------------------
# Offline mode
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    dsn = _get_dsn()
    context.configure(
        url=dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Dedicated revision table: platform-ml shares its database with other
        # services (e.g. platform-connectors). Using the default ``alembic_version``
        # made them overwrite each other's head. Keep ML's history isolated.
        version_table="alembic_version_ml",
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    dsn = _get_dsn()
    connectable = create_engine(
        dsn,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # See note in run_migrations_offline: isolate ML's revision history
            # from co-located services sharing the same database.
            version_table="alembic_version_ml",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
