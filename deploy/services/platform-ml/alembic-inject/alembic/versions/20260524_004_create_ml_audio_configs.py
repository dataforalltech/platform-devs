"""Create ml_audio_configs table

Revision ID: 20260524_004
Revises: 20260523_003
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260524_004"
down_revision = "20260523_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    mysql = bind.dialect.name == "mysql"

    # ── Create ml_audio_configs table ─────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audio_configs (
                config_id      VARCHAR(64)   NOT NULL,
                name           VARCHAR(255)  NOT NULL,
                description    TEXT,
                operation      VARCHAR(64)   NOT NULL,
                provider       VARCHAR(64)   NOT NULL,
                connector_id   VARCHAR(255),
                language       VARCHAR(32),
                voice_id       VARCHAR(255),
                model_size     VARCHAR(32),
                speaker_labels TINYINT(1)    NOT NULL DEFAULT 0,
                output_format  VARCHAR(32),
                tags           VARCHAR(512),
                is_active      TINYINT(1)    NOT NULL DEFAULT 1,
                scope          VARCHAR(64)   NOT NULL DEFAULT 'default',
                created_by     VARCHAR(255),
                created_at     VARCHAR(64),
                updated_at     VARCHAR(64),
                PRIMARY KEY (config_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # MySQL < 8.0.1 doesn't support CREATE INDEX — check manually
        idx_r = bind.execute(text("""
            SELECT COUNT(*) FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'ml_audio_configs'
              AND index_name = 'idx_ml_audio_configs_scope'
        """))
        if (idx_r.fetchone() or [0])[0] == 0:
            op.execute(
                "CREATE INDEX idx_ml_audio_configs_scope "
                "ON ml_audio_configs (scope, is_active)"
            )
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audio_configs (
                config_id      TEXT          NOT NULL,
                name           TEXT          NOT NULL,
                description    TEXT,
                operation      TEXT          NOT NULL,
                provider       TEXT          NOT NULL,
                connector_id   TEXT,
                language       TEXT,
                voice_id       TEXT,
                model_size     TEXT,
                speaker_labels INTEGER       NOT NULL DEFAULT 0,
                output_format  TEXT,
                tags           TEXT,
                is_active      INTEGER       NOT NULL DEFAULT 1,
                scope          TEXT          NOT NULL DEFAULT 'default',
                created_by     TEXT,
                created_at     TEXT,
                updated_at     TEXT,
                PRIMARY KEY (config_id)
            )
        """)
        op.execute(
            "CREATE INDEX idx_ml_audio_configs_scope "
            "ON ml_audio_configs (scope, is_active)"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_audio_configs")
