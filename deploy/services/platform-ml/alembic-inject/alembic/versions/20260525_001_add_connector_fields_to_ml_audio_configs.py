"""Add connector_id and connector_ids to ml_audio_configs

Revision ID: 20260525_001
Revises: 38c539394d14
Create Date: 2026-05-25
"""
from alembic import op
from sqlalchemy import text

revision = "20260525_001"
down_revision = "38c539394d14"
branch_labels = None
depends_on = None


def _column_exists(bind, table: str, column: str) -> bool:
    r = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        f"WHERE table_schema = DATABASE() "
        f"AND table_name = '{table}' AND column_name = '{column}'"
    ))
    return bool((r.fetchone() or [0])[0])


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "ml_audio_configs", "connector_id"):
        op.execute(text(
            "ALTER TABLE ml_audio_configs ADD COLUMN connector_id VARCHAR(255) NULL"
        ))
    if not _column_exists(bind, "ml_audio_configs", "connector_ids"):
        op.execute(text(
            "ALTER TABLE ml_audio_configs ADD COLUMN connector_ids TEXT NULL"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    if _column_exists(bind, "ml_audio_configs", "connector_ids"):
        op.execute(text("ALTER TABLE ml_audio_configs DROP COLUMN connector_ids"))
    if _column_exists(bind, "ml_audio_configs", "connector_id"):
        op.execute(text("ALTER TABLE ml_audio_configs DROP COLUMN connector_id"))
