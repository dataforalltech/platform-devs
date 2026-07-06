"""create ml_vision_jobs table

Revision ID: 20260522_002
Revises: 20260522_001
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa

revision = "20260522_002"
down_revision = "20260522_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    mysql = conn.dialect.name == "mysql"

    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_vision_jobs (
                job_id      VARCHAR(64)   PRIMARY KEY,
                status      VARCHAR(32)   NOT NULL DEFAULT 'queued',
                progress    INT           NOT NULL DEFAULT 0,
                step        VARCHAR(255)  NULL,
                operation   VARCHAR(64)   NOT NULL DEFAULT 'detect_labels',
                provider    VARCHAR(64)   NOT NULL DEFAULT 'local',
                filename    VARCHAR(512)  NOT NULL DEFAULT '',
                file_size   INT           NOT NULL DEFAULT 0,
                label_count INT           NOT NULL DEFAULT 0,
                result      LONGTEXT      NULL,
                error       TEXT          NULL,
                created_by  VARCHAR(255)  NOT NULL DEFAULT '',
                created_at  VARCHAR(64)   NOT NULL DEFAULT '',
                updated_at  VARCHAR(64)   NOT NULL DEFAULT '',
                started_at  VARCHAR(64)   NULL,
                ended_at    VARCHAR(64)   NULL,
                duration_ms INT           NOT NULL DEFAULT 0,
                scope       VARCHAR(128)  NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_vision_jobs_scope ON ml_vision_jobs (scope, created_at)")
        op.execute("CREATE INDEX idx_vision_jobs_status ON ml_vision_jobs (status, created_at)")
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_vision_jobs (
                job_id      TEXT          PRIMARY KEY,
                status      TEXT          NOT NULL DEFAULT 'queued',
                progress    INTEGER       NOT NULL DEFAULT 0,
                step        TEXT,
                operation   TEXT          NOT NULL DEFAULT 'detect_labels',
                provider    TEXT          NOT NULL DEFAULT 'local',
                filename    TEXT          NOT NULL DEFAULT '',
                file_size   INTEGER       NOT NULL DEFAULT 0,
                label_count INTEGER       NOT NULL DEFAULT 0,
                result      JSONB,
                error       TEXT,
                created_by  TEXT          NOT NULL DEFAULT '',
                created_at  TEXT          NOT NULL DEFAULT '',
                updated_at  TEXT          NOT NULL DEFAULT '',
                started_at  TEXT,
                ended_at    TEXT,
                duration_ms INTEGER       NOT NULL DEFAULT 0,
                scope       VARCHAR(128)  NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_vision_jobs_scope ON ml_vision_jobs (scope, created_at)")
        op.execute("CREATE INDEX idx_vision_jobs_status ON ml_vision_jobs (status, created_at)")

    # Also widen result column in ml_vision_history if MySQL (was TEXT, now LONGTEXT)
    if mysql:
        op.execute("ALTER TABLE ml_vision_history MODIFY COLUMN result LONGTEXT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_vision_jobs")
