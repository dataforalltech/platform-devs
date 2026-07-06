"""create per-module RUN tables and add run_id to jobs

Revision ID: 20260531_006
Revises: 20260531_005
Create Date: 2026-05-31

Introduces the RUN concept (logical execution/result) for the processing
modules that previously only had JOBs, per the canonical process model
(docs/ML_PROCESS_MODEL_CONTRACT.md). Training keeps its richer ml_runs table.

  creates: ml_file_runs, ml_audio_runs, ml_nlp_runs, ml_vision_runs
  alters : ml_file_jobs, ml_audio_jobs, ml_nlp_jobs, ml_vision_jobs  (+ run_id)
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260531_006"
down_revision: Union[str, None] = "20260531_005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUN_TABLES = ["ml_file_runs", "ml_audio_runs", "ml_nlp_runs", "ml_vision_runs"]
_JOB_TABLES = ["ml_file_jobs", "ml_audio_jobs", "ml_nlp_jobs", "ml_vision_jobs"]


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


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        sql = (
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        )
    else:
        sql = (
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        )
    row = bind.execute(text(sql), {"t": table, "c": column}).fetchone()
    return bool(row and row[0])


def _create_run_table(table: str) -> None:
    if _is_mysql():
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                run_id            VARCHAR(64)  PRIMARY KEY,
                job_id            VARCHAR(64)  NOT NULL,
                status            VARCHAR(32)  NOT NULL DEFAULT 'completed',
                operation         VARCHAR(64)  NULL,
                provider          VARCHAR(64)  NULL,
                parameters        JSON         NULL,
                metrics           JSON         NULL,
                result            LONGTEXT     NULL,
                input_fingerprint VARCHAR(128) NULL,
                project_id        VARCHAR(64)  NULL,
                started_at        VARCHAR(64)  NULL,
                ended_at          VARCHAR(64)  NULL,
                duration_ms       INT          NULL,
                created_by        VARCHAR(255) NOT NULL DEFAULT '',
                created_at        VARCHAR(64)  NOT NULL DEFAULT '',
                scope             VARCHAR(64)  NOT NULL DEFAULT 'default',
                INDEX idx_{table}_job (job_id),
                INDEX idx_{table}_scope (scope, created_at DESC)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                run_id            VARCHAR(64)  PRIMARY KEY,
                job_id            VARCHAR(64)  NOT NULL,
                status            VARCHAR(32)  NOT NULL DEFAULT 'completed',
                operation         VARCHAR(64),
                provider          VARCHAR(64),
                parameters        JSONB,
                metrics           JSONB,
                result            JSONB,
                input_fingerprint VARCHAR(128),
                project_id        VARCHAR(64),
                started_at        VARCHAR(64),
                ended_at          VARCHAR(64),
                duration_ms       INTEGER,
                created_by        VARCHAR(255) NOT NULL DEFAULT '',
                created_at        VARCHAR(64)  NOT NULL DEFAULT '',
                scope             VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
        op.execute(f"CREATE INDEX idx_{table}_job ON {table} (job_id)")
        op.execute(f"CREATE INDEX idx_{table}_scope ON {table} (scope, created_at DESC)")


def _add_run_id(table: str) -> None:
    if not _table_exists(table) or _has_column(table, "run_id"):
        return
    if _is_mysql():
        op.execute(f"ALTER TABLE {table} ADD COLUMN run_id VARCHAR(64) NULL")
    else:
        op.execute(f"ALTER TABLE {table} ADD COLUMN run_id VARCHAR(64)")


def upgrade() -> None:
    for table in _RUN_TABLES:
        _create_run_table(table)
    for table in _JOB_TABLES:
        _add_run_id(table)


def downgrade() -> None:
    for table in _JOB_TABLES:
        if _table_exists(table) and _has_column(table, "run_id"):
            op.execute(f"ALTER TABLE {table} DROP COLUMN run_id")
    for table in _RUN_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
