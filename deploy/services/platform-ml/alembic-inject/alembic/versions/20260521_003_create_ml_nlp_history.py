"""create ml_nlp_history and ml_nlp_jobs tables

Revision ID: 20260521_003
Revises: 20260521_002
Create Date: 2026-05-21

ml_nlp_history — stores NLP analysis results per operation call.
ml_nlp_jobs    — tracks async NLP processing jobs.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260521_003"
down_revision: Union[str, None] = "20260521_002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_nlp_history (
                id           VARCHAR(64)  PRIMARY KEY,
                operation    VARCHAR(64)  NOT NULL COMMENT 'sentiment | entities | sentences | keywords',
                provider     VARCHAR(64)  NOT NULL,
                language     VARCHAR(16)  NOT NULL DEFAULT 'en',
                text_preview TEXT         NOT NULL,
                text_length  INT          NOT NULL DEFAULT 0,
                result       JSON         NOT NULL,
                status       VARCHAR(32)  NOT NULL DEFAULT 'success' COMMENT 'success | error',
                started_at   VARCHAR(64)  NOT NULL DEFAULT '',
                ended_at     VARCHAR(64)  NOT NULL DEFAULT '',
                duration_ms  INT          NOT NULL DEFAULT 0,
                error        TEXT         NULL,
                created_by   VARCHAR(255) NOT NULL DEFAULT '',
                created_at   VARCHAR(64)  NOT NULL DEFAULT '',
                scope        VARCHAR(64)  NOT NULL DEFAULT 'default',
                INDEX idx_ml_nlp_history_scope (scope, created_at DESC),
                INDEX idx_ml_nlp_history_op (operation, provider),
                INDEX idx_ml_nlp_history_status (status, created_at DESC)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_nlp_history (
                id           TEXT PRIMARY KEY,
                operation    TEXT NOT NULL,
                provider     TEXT NOT NULL,
                language     TEXT NOT NULL DEFAULT 'en',
                text_preview TEXT NOT NULL DEFAULT '',
                text_length  INTEGER NOT NULL DEFAULT 0,
                result       JSONB NOT NULL DEFAULT '{}'::jsonb,
                status       TEXT NOT NULL DEFAULT 'success',
                started_at   TEXT NOT NULL DEFAULT '',
                ended_at     TEXT NOT NULL DEFAULT '',
                duration_ms  INTEGER NOT NULL DEFAULT 0,
                error        TEXT,
                created_by   TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT '',
                scope        VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_nlp_history_scope ON ml_nlp_history (scope, created_at DESC)")
        op.execute("CREATE INDEX idx_ml_nlp_history_op ON ml_nlp_history (operation, provider)")
        op.execute("CREATE INDEX idx_ml_nlp_history_status ON ml_nlp_history (status, created_at DESC)")


    # ── ml_nlp_jobs ───────────────────────────────────────────────────────────
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_nlp_jobs (
                job_id      VARCHAR(64)  PRIMARY KEY,
                status      VARCHAR(32)  NOT NULL DEFAULT 'queued' COMMENT 'queued | running | completed | failed | cancelled',
                operation   VARCHAR(64)  NOT NULL COMMENT 'sentiment | entities | sentences | keywords',
                provider    VARCHAR(64)  NOT NULL,
                language    VARCHAR(16)  NOT NULL DEFAULT 'en',
                text_length INT          NOT NULL DEFAULT 0,
                result      JSON         NULL,
                error       TEXT         NULL,
                created_by  VARCHAR(255) NOT NULL DEFAULT '',
                created_at  VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at  VARCHAR(64)  NOT NULL DEFAULT '',
                started_at  VARCHAR(64)  NULL,
                ended_at    VARCHAR(64)  NULL,
                scope       VARCHAR(64)  NOT NULL DEFAULT 'default',
                INDEX idx_ml_nlp_jobs_scope (scope, created_at DESC),
                INDEX idx_ml_nlp_jobs_status (status, created_at)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_nlp_jobs (
                job_id      TEXT PRIMARY KEY,
                status      TEXT NOT NULL DEFAULT 'queued',
                operation   TEXT NOT NULL,
                provider    TEXT NOT NULL,
                language    TEXT NOT NULL DEFAULT 'en',
                text_length INTEGER NOT NULL DEFAULT 0,
                result      JSONB,
                error       TEXT,
                created_by  TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT '',
                started_at  TEXT,
                ended_at    TEXT,
                scope       VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_nlp_jobs_scope ON ml_nlp_jobs (scope, created_at DESC)")
        op.execute("CREATE INDEX idx_ml_nlp_jobs_status ON ml_nlp_jobs (status, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_nlp_jobs")
    op.execute("DROP TABLE IF EXISTS ml_nlp_history")
