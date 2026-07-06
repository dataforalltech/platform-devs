"""create ml_vision_config table

Revision ID: 20260524_006
Revises: 20260524_005
Create Date: 2026-05-24
"""
from alembic import op
from sqlalchemy import text

revision = "20260524_006"
down_revision = "20260524_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS ml_vision_config (
            config_id            VARCHAR(64)   NOT NULL,
            name                 VARCHAR(255)  NOT NULL,
            description          TEXT,
            operation            VARCHAR(64)   NOT NULL,
            provider             VARCHAR(64)   NOT NULL,
            confidence_threshold DECIMAL(4,3),
            connector_id         VARCHAR(255),
            tags                 VARCHAR(512),
            is_active            TINYINT(1)    NOT NULL DEFAULT 1,
            scope                VARCHAR(64)   NOT NULL DEFAULT 'default',
            created_by           VARCHAR(255),
            created_at           VARCHAR(64),
            updated_at           VARCHAR(64),
            PRIMARY KEY (config_id)
        )
    """))
    # MySQL < 8.0.1 doesn't support CREATE INDEX
    if bind.dialect.name == "mysql":
        r = bind.execute(text(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'ml_vision_config' "
            "AND index_name = 'ix_ml_vision_config_scope_active'"
        ))
        if (r.fetchone() or [0])[0] == 0:
            op.execute(text(
                "CREATE INDEX ix_ml_vision_config_scope_active "
                "ON ml_vision_config (scope, is_active)"
            ))
    else:
        op.execute(text(
            "CREATE INDEX ix_ml_vision_config_scope_active "
            "ON ml_vision_config (scope, is_active)"
        ))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS ml_vision_config"))
