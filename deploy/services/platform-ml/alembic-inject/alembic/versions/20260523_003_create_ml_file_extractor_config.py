"""Create ml_file_extractor config table and add config_id to jobs

Revision ID: 20260523_003
Revises: 20260523_001
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260523_003"
down_revision = "20260523_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    mysql = bind.dialect.name == "mysql"

    # ── 1. Create ml_file_extractor config table ──────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_file_extractor (
                config_id          VARCHAR(64)   NOT NULL,
                name               VARCHAR(255)  NOT NULL,
                description        TEXT,
                provider           VARCHAR(64)   NOT NULL DEFAULT 'local',
                connector_id       VARCHAR(255),
                operations         VARCHAR(512)  NOT NULL DEFAULT 'extract_text',
                allowed_file_types VARCHAR(512),
                max_file_size_kb   INT,
                timeout_seconds    INT,
                tags               VARCHAR(512),
                is_active          TINYINT(1)    NOT NULL DEFAULT 1,
                scope              VARCHAR(64)   NOT NULL DEFAULT 'default',
                created_by         VARCHAR(255),
                created_at         VARCHAR(64),
                updated_at         VARCHAR(64),
                PRIMARY KEY (config_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # MySQL < 8.0.1 doesn't support CREATE INDEX — check manually
        idx_result = bind.execute(text("""
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'ml_file_extractor'
              AND index_name = 'idx_ml_file_extractor_scope'
        """))
        idx_row = idx_result.fetchone()
        if (idx_row[0] if idx_row else 0) == 0:
            op.execute(
                "CREATE INDEX idx_ml_file_extractor_scope "
                "ON ml_file_extractor (scope, is_active)"
            )
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_file_extractor (
                config_id          TEXT          NOT NULL,
                name               TEXT          NOT NULL,
                description        TEXT,
                provider           TEXT          NOT NULL DEFAULT 'local',
                connector_id       TEXT,
                operations         TEXT          NOT NULL DEFAULT 'extract_text',
                allowed_file_types TEXT,
                max_file_size_kb   INTEGER,
                timeout_seconds    INTEGER,
                tags               TEXT,
                is_active          INTEGER       NOT NULL DEFAULT 1,
                scope              TEXT          NOT NULL DEFAULT 'default',
                created_by         TEXT,
                created_at         TEXT,
                updated_at         TEXT,
                PRIMARY KEY (config_id)
            )
        """)
        op.execute(
            "CREATE INDEX idx_ml_file_extractor_scope "
            "ON ml_file_extractor (scope, is_active)"
        )

    # ── 2. Add config_id column to ml_file_extract_jobs ────────────────────
    if mysql:
        # MySQL doesn't support IF NOT EXISTS for ADD COLUMN — check first
        result = bind.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'ml_file_extract_jobs'
              AND column_name = 'config_id'
        """))
        row = result.fetchone()
        if (row[0] if row else 0) == 0:
            op.execute(
                "ALTER TABLE ml_file_extract_jobs "
                "ADD COLUMN config_id VARCHAR(64) NULL"
            )
    else:
        op.execute(
            "ALTER TABLE ml_file_extract_jobs "
            "ADD COLUMN config_id TEXT NULL"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_file_extractor")
    op.execute(
        "ALTER TABLE ml_file_extract_jobs DROP COLUMN config_id"
    )
