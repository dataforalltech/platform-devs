"""Create ml_training_job_stages table and add stage tracking columns to ml_training_jobs

Revision ID: 20260529_006
Revises: 20260529_005
Create Date: 2026-05-29

Creates ml_training_job_stages table (granular per-stage log for training jobs).
Adds current_stage and progress_pct columns to ml_training_jobs (idempotent).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260529_006"
down_revision: Union[str, None] = "20260529_005"
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


def upgrade() -> None:
    mysql = _is_mysql()

    # ── ml_training_job_stages ────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_training_job_stages (
                id           BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
                job_id       VARCHAR(64)   NOT NULL,
                stage        VARCHAR(64)   NOT NULL,
                status       VARCHAR(32)   NOT NULL DEFAULT 'running',
                started_at   VARCHAR(64)   NOT NULL,
                ended_at     VARCHAR(64)   NULL,
                duration_ms  INT           NULL,
                error        TEXT          NULL,
                INDEX idx_ml_job_stages_job (job_id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_training_job_stages (
                id           BIGSERIAL     PRIMARY KEY,
                job_id       TEXT          NOT NULL,
                stage        TEXT          NOT NULL,
                status       TEXT          NOT NULL DEFAULT 'running',
                started_at   TEXT          NOT NULL,
                ended_at     TEXT,
                duration_ms  INTEGER,
                error        TEXT
            )
        """)
        op.execute(
            "CREATE INDEX idx_ml_job_stages_job ON ml_training_job_stages (job_id)"
        )

    # ── Add current_stage column to ml_training_jobs (idempotent) ────────────
    if not _column_exists("ml_training_jobs", "current_stage"):
        if mysql:
            op.execute(
                "ALTER TABLE ml_training_jobs ADD COLUMN current_stage VARCHAR(64) NULL"
            )
        else:
            op.execute(
                "ALTER TABLE ml_training_jobs ADD COLUMN current_stage TEXT"
            )

    # ── Add progress_pct column to ml_training_jobs (idempotent) ─────────────
    if not _column_exists("ml_training_jobs", "progress_pct"):
        if mysql:
            op.execute(
                "ALTER TABLE ml_training_jobs ADD COLUMN progress_pct INT NOT NULL DEFAULT 0"
            )
        else:
            op.execute(
                "ALTER TABLE ml_training_jobs ADD COLUMN progress_pct INTEGER NOT NULL DEFAULT 0"
            )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_training_job_stages")
    # Note: we intentionally do NOT drop the columns from ml_training_jobs
    # as ALTER TABLE DROP COLUMN can be risky in production rollbacks.
