"""create ml_audio_jobs table

Revision ID: 20260531_002
Revises: 20260531_001
Create Date: 2026-05-31

``ml_audio_jobs`` is read/written by ``MLMetadataStore`` (create_audio_job,
update_audio_job, get_audio_job, list_audio_jobs) but had no migration, so a
clean database lacked the table. Columns mirror exactly what those methods
reference. Schema kept aligned with the canonical JOB contract
(see docs/ML_PROCESS_MODEL_CONTRACT.md).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260531_002"
down_revision: Union[str, None] = "20260531_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audio_jobs (
                job_id      VARCHAR(64)  PRIMARY KEY,
                operation   VARCHAR(64)  NOT NULL COMMENT 'transcribe | synthesize | clone | s2s',
                provider    VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'queued' COMMENT 'queued | running | completed | failed | cancelled',
                progress    INT          NOT NULL DEFAULT 0,
                step        VARCHAR(255) NULL,
                input_ref   TEXT         NULL,
                output_path TEXT         NULL,
                transcript  LONGTEXT     NULL,
                details     JSON         NULL,
                error       TEXT         NULL,
                created_by  VARCHAR(255) NOT NULL DEFAULT '',
                created_at  VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at  VARCHAR(64)  NOT NULL DEFAULT '',
                started_at  VARCHAR(64)  NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INT          NULL,
                language    VARCHAR(32)  NULL,
                char_count  INT          NULL,
                input_size  INT          NULL,
                output_size INT          NULL,
                scope       VARCHAR(64)  NOT NULL DEFAULT 'default',
                INDEX idx_ml_audio_jobs_scope (scope, created_at DESC),
                INDEX idx_ml_audio_jobs_status (status, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audio_jobs (
                job_id      TEXT PRIMARY KEY,
                operation   TEXT NOT NULL,
                provider    TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'queued',
                progress    INTEGER NOT NULL DEFAULT 0,
                step        TEXT,
                input_ref   TEXT,
                output_path TEXT,
                transcript  TEXT,
                details     JSONB,
                error       TEXT,
                created_by  TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT '',
                started_at  TEXT,
                ended_at    TEXT,
                duration_ms INTEGER,
                language    TEXT,
                char_count  INTEGER,
                input_size  INTEGER,
                output_size INTEGER,
                scope       VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_audio_jobs_scope ON ml_audio_jobs (scope, created_at DESC)")
        op.execute("CREATE INDEX idx_ml_audio_jobs_status ON ml_audio_jobs (status, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_audio_jobs")
