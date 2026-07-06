"""add provider column to ml_file_extract_history

Revision ID: 20260523_001
Revises: 20260522_002_create_ml_vision_jobs
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op

revision = "20260523_001"
down_revision = "20260522_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Detect engine from dialect
    bind = op.get_bind()
    mysql = bind.dialect.name == "mysql"

    if mysql:
        op.execute(
            "ALTER TABLE ml_file_extract_history "
            "ADD COLUMN provider VARCHAR(64) NOT NULL DEFAULT 'local'"
        )
    else:
        op.execute(
            "ALTER TABLE ml_file_extract_history "
            "ADD COLUMN provider TEXT NOT NULL DEFAULT 'local'"
        )
        op.execute(
            "CREATE INDEX idx_ml_file_history_provider "
            "ON ml_file_extract_history (provider)"
        )


def downgrade() -> None:
    op.execute("ALTER TABLE ml_file_extract_history DROP COLUMN provider")
