"""align ml_file_history to canonical HISTORY contract

Revision ID: 20260531_007
Revises: 20260531_006
Create Date: 2026-05-31

Per docs/ML_PROCESS_MODEL_CONTRACT.md, HISTORY tables use PK ``id`` and carry
``operation`` and ``status``. ml_file_history was the outlier (PK ``extract_id``,
no operation/status). This renames the PK column and adds the two columns.
Also drops the now-redundant ``step_timings`` column from ml_file_jobs (timing
lives in ml_file_stages). Clean cut — no compatibility view.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260531_007"
down_revision: Union[str, None] = "20260531_006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


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


def upgrade() -> None:
    mysql = _is_mysql()

    # 1) ml_file_history: rename extract_id -> id, add operation + status
    if _has_column("ml_file_history", "extract_id") and not _has_column("ml_file_history", "id"):
        if mysql:
            op.execute("ALTER TABLE ml_file_history CHANGE COLUMN extract_id id VARCHAR(64) NOT NULL")
        else:
            op.execute("ALTER TABLE ml_file_history RENAME COLUMN extract_id TO id")

    if not _has_column("ml_file_history", "operation"):
        if mysql:
            op.execute("ALTER TABLE ml_file_history ADD COLUMN operation VARCHAR(64) NOT NULL DEFAULT 'extract_text'")
        else:
            op.execute("ALTER TABLE ml_file_history ADD COLUMN operation VARCHAR(64) NOT NULL DEFAULT 'extract_text'")

    if not _has_column("ml_file_history", "status"):
        if mysql:
            op.execute("ALTER TABLE ml_file_history ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'success'")
        else:
            op.execute("ALTER TABLE ml_file_history ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'success'")

    # 2) ml_file_jobs: drop redundant step_timings (timing lives in ml_file_stages)
    if _has_column("ml_file_jobs", "step_timings"):
        if mysql:
            op.execute("ALTER TABLE ml_file_jobs DROP COLUMN step_timings")
        else:
            op.execute("ALTER TABLE ml_file_jobs DROP COLUMN step_timings")


def downgrade() -> None:
    mysql = _is_mysql()

    # Restore step_timings
    if not _has_column("ml_file_jobs", "step_timings"):
        if mysql:
            op.execute("ALTER TABLE ml_file_jobs ADD COLUMN step_timings JSON NULL")
        else:
            op.execute("ALTER TABLE ml_file_jobs ADD COLUMN step_timings JSONB")

    # Drop operation/status, rename id -> extract_id
    if _has_column("ml_file_history", "status"):
        op.execute("ALTER TABLE ml_file_history DROP COLUMN status")
    if _has_column("ml_file_history", "operation"):
        op.execute("ALTER TABLE ml_file_history DROP COLUMN operation")
    if _has_column("ml_file_history", "id") and not _has_column("ml_file_history", "extract_id"):
        if mysql:
            op.execute("ALTER TABLE ml_file_history CHANGE COLUMN id extract_id VARCHAR(64) NOT NULL")
        else:
            op.execute("ALTER TABLE ml_file_history RENAME COLUMN id TO extract_id")
