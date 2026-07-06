"""add progress and step columns to ml_nlp_jobs

Revision ID: 20260531_003
Revises: 20260531_002
Create Date: 2026-05-31

``NlpJobStore.update`` already writes ``progress`` and ``step`` but the table
never had those columns, so live-progress updates failed. This aligns
ml_nlp_jobs with the canonical JOB contract so it can drive the shared
JobStatusBanner like the other modules.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260531_003"
down_revision: Union[str, None] = "20260531_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _mysql_has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return bool(row and row[0])


def upgrade() -> None:
    if _is_mysql():
        if not _mysql_has_column("ml_nlp_jobs", "progress"):
            op.execute("ALTER TABLE ml_nlp_jobs ADD COLUMN progress INT NOT NULL DEFAULT 0")
        if not _mysql_has_column("ml_nlp_jobs", "step"):
            op.execute("ALTER TABLE ml_nlp_jobs ADD COLUMN step VARCHAR(255) NULL")
    else:
        op.execute("ALTER TABLE ml_nlp_jobs ADD COLUMN progress INTEGER NOT NULL DEFAULT 0")
        op.execute("ALTER TABLE ml_nlp_jobs ADD COLUMN step TEXT")


def downgrade() -> None:
    # MySQL doesn't support DROP COLUMN — guard via information_schema.
    if _is_mysql():
        if _mysql_has_column("ml_nlp_jobs", "step"):
            op.execute("ALTER TABLE ml_nlp_jobs DROP COLUMN step")
        if _mysql_has_column("ml_nlp_jobs", "progress"):
            op.execute("ALTER TABLE ml_nlp_jobs DROP COLUMN progress")
    else:
        op.execute("ALTER TABLE ml_nlp_jobs DROP COLUMN step")
        op.execute("ALTER TABLE ml_nlp_jobs DROP COLUMN progress")
