"""split ml_processing_stages into per-module stage tables

Revision ID: 20260531_004
Revises: 20260531_003
Create Date: 2026-05-31

Per the canonical process model (docs/ML_PROCESS_MODEL_CONTRACT.md), each module
owns its STAGE table ``ml_<module>_stages`` instead of the shared
``ml_processing_stages``. Schema is identical across modules (minus the
``module`` discriminator column) so the frontend keeps reusing JobStatusBanner.

Existing rows are copied into the matching per-module table (partitioned by the
old ``module`` column) before the shared table is dropped. Clean cut: no
compatibility view is left behind.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260531_004"
down_revision: Union[str, None] = "20260531_003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# old module label -> new per-module table
_MODULE_TABLES = {
    "files": "ml_file_stages",
    "audio": "ml_audio_stages",
    "nlp": "ml_nlp_stages",
    "vision": "ml_vision_stages",
    "ml_training": "ml_training_stages",
}


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        sql = (
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = :t"
        )
    else:
        sql = "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :t"
    row = bind.execute(text(sql), {"t": table}).fetchone()
    return bool(row and row[0])


def _create_table(table: str) -> None:
    if _is_mysql():
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
                job_id      VARCHAR(64)  NOT NULL,
                stage       VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'running',
                started_at  VARCHAR(64)  NOT NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INT          NULL,
                error       TEXT         NULL,
                INDEX idx_{table}_job (job_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id          BIGSERIAL    PRIMARY KEY,
                job_id      VARCHAR(64)  NOT NULL,
                stage       VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'running',
                started_at  VARCHAR(64)  NOT NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INTEGER      NULL,
                error       TEXT         NULL
            )
        """)
        op.execute(f"CREATE INDEX idx_{table}_job ON {table} (job_id)")


def upgrade() -> None:
    has_source = _table_exists("ml_processing_stages")

    bind = op.get_bind()
    for module, table in _MODULE_TABLES.items():
        _create_table(table)
        if has_source:
            # Copy existing rows for this module (preserve history, not a view).
            # NOTE: op.execute() takes no params — use the bound Connection.
            bind.execute(
                text(
                    f"INSERT INTO {table} "  # noqa: S608
                    f"(job_id, stage, status, started_at, ended_at, duration_ms, error) "
                    f"SELECT job_id, stage, status, started_at, ended_at, duration_ms, error "
                    f"FROM ml_processing_stages WHERE module = :m"
                ),
                {"m": module},
            )

    if has_source:
        op.execute("DROP TABLE IF EXISTS ml_processing_stages")


def downgrade() -> None:
    # Recreate the shared table and fold per-module rows back into it.
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_processing_stages (
                id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
                module      VARCHAR(32)  NOT NULL,
                job_id      VARCHAR(64)  NOT NULL,
                stage       VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'running',
                started_at  VARCHAR(64)  NOT NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INT          NULL,
                error       TEXT         NULL,
                INDEX idx_processing_stages_job (module, job_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_processing_stages (
                id          BIGSERIAL    PRIMARY KEY,
                module      VARCHAR(32)  NOT NULL,
                job_id      VARCHAR(64)  NOT NULL,
                stage       VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'running',
                started_at  VARCHAR(64)  NOT NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INTEGER      NULL,
                error       TEXT         NULL
            )
        """)
        op.execute(
            "CREATE INDEX idx_processing_stages_job "
            "ON ml_processing_stages (module, job_id)"
        )

    bind = op.get_bind()
    for module, table in _MODULE_TABLES.items():
        if _table_exists(table):
            bind.execute(
                text(
                    f"INSERT INTO ml_processing_stages "  # noqa: S608
                    f"(module, job_id, stage, status, started_at, ended_at, duration_ms, error) "
                    f"SELECT :m, job_id, stage, status, started_at, ended_at, duration_ms, error "
                    f"FROM {table}"
                ),
                {"m": module},
            )
            op.execute(f"DROP TABLE IF EXISTS {table}")
