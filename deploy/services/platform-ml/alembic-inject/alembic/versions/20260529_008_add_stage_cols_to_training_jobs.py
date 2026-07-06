"""Add current_stage and progress_pct columns to ml_training_jobs

Revision ID: 20260529_008
Revises: 38c539394d14
Create Date: 2026-05-29

Adds two columns to ml_training_jobs for live stage tracking:
  - current_stage VARCHAR(64) NULL
  - progress_pct  INT NOT NULL DEFAULT 0

Also creates ml_processing_stages table used by ProcessingStageStore
(shared stage log for all modules including ml_training).

Both operations are idempotent via information_schema checks.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260529_008"
down_revision: Union[str, None] = "38c539394d14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        result = bind.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
    else:
        result = bind.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        )
    row = result.fetchone()
    return bool(row and row[0])


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        result = bind.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = :t"
            ),
            {"t": table},
        )
    else:
        result = bind.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :t"
            ),
            {"t": table},
        )
    row = result.fetchone()
    return bool(row and row[0])


def upgrade() -> None:
    mysql = _is_mysql()

    # ── Add current_stage column to ml_training_jobs (idempotent) ────────────
    if not _column_exists("ml_training_jobs", "current_stage"):
        if mysql:
            op.execute(text(
                "ALTER TABLE ml_training_jobs ADD COLUMN current_stage VARCHAR(64) NULL"
            ))
        else:
            op.execute(text(
                "ALTER TABLE ml_training_jobs ADD COLUMN current_stage VARCHAR(64)"
            ))

    # ── Add progress_pct column to ml_training_jobs (idempotent) ─────────────
    if not _column_exists("ml_training_jobs", "progress_pct"):
        if mysql:
            op.execute(text(
                "ALTER TABLE ml_training_jobs ADD COLUMN progress_pct INT NOT NULL DEFAULT 0"
            ))
        else:
            op.execute(text(
                "ALTER TABLE ml_training_jobs ADD COLUMN progress_pct INTEGER NOT NULL DEFAULT 0"
            ))

    # ── Create ml_processing_stages table (shared stage log) ─────────────────
    if not _table_exists("ml_processing_stages"):
        if mysql:
            op.execute(text("""
                CREATE TABLE ml_processing_stages (
                    id          BIGINT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    module      VARCHAR(32)     NOT NULL,
                    job_id      VARCHAR(64)     NOT NULL,
                    stage       VARCHAR(64)     NOT NULL,
                    status      VARCHAR(32)     NOT NULL DEFAULT 'running',
                    started_at  VARCHAR(64)     NOT NULL,
                    ended_at    VARCHAR(64)     NULL,
                    duration_ms INT             NULL,
                    error       TEXT            NULL,
                    INDEX idx_processing_stages_job (module, job_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
        else:
            op.execute(text("""
                CREATE TABLE ml_processing_stages (
                    id          BIGSERIAL       PRIMARY KEY,
                    module      VARCHAR(32)     NOT NULL,
                    job_id      VARCHAR(64)     NOT NULL,
                    stage       VARCHAR(64)     NOT NULL,
                    status      VARCHAR(32)     NOT NULL DEFAULT 'running',
                    started_at  VARCHAR(64)     NOT NULL,
                    ended_at    VARCHAR(64)     NULL,
                    duration_ms INTEGER         NULL,
                    error       TEXT            NULL
                )
            """))
            op.execute(text(
                "CREATE INDEX idx_processing_stages_job "
                "ON ml_processing_stages (module, job_id)"
            ))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS ml_processing_stages"))
    # Note: we intentionally do NOT drop current_stage / progress_pct from
    # ml_training_jobs as ALTER TABLE DROP COLUMN can be risky in production.
