"""Create ml_processing_stages — shared stage-log table for Audio, NLP, Files, Vision

Revision ID: 20260529_007
Revises: 20260529_006, 20260525_003, 20260525_005
Create Date: 2026-05-29

One row per stage per job for every module (audio, nlp, files, vision).
Columns identical to ml_training_job_stages so the frontend reuses the same
JobStatusBanner component with no extra adaptation.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260529_007"
down_revision: Union[str, tuple[str, ...], None] = (
    "20260529_006",
    "20260525_003",
    "20260525_005",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


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
    if _table_exists("ml_processing_stages"):
        return

    if _is_mysql():
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
