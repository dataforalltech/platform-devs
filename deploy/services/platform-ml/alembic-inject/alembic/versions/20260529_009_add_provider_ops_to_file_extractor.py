"""Add provider and operations columns to ml_file_extractor

Revision ID: 20260529_009
Revises: 20260529_008
Create Date: 2026-05-29
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260529_009"
down_revision = "20260529_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    mysql = bind.dialect.name == "mysql"

    if mysql:
        result = bind.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'ml_file_extractor'
              AND column_name = 'provider'
        """))
        row = result.fetchone()
        if (row[0] if row else 0) == 0:
            op.execute(
                "ALTER TABLE ml_file_extractor "
                "ADD COLUMN provider VARCHAR(64) NOT NULL DEFAULT 'local'"
            )

        result2 = bind.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'ml_file_extractor'
              AND column_name = 'operations'
        """))
        row2 = result2.fetchone()
        if (row2[0] if row2 else 0) == 0:
            op.execute(
                "ALTER TABLE ml_file_extractor "
                "ADD COLUMN operations VARCHAR(512) NOT NULL DEFAULT 'extract_text'"
            )
    else:
        op.execute(
            "ALTER TABLE ml_file_extractor "
            "ADD COLUMN provider TEXT NOT NULL DEFAULT 'local'"
        )
        op.execute(
            "ALTER TABLE ml_file_extractor "
            "ADD COLUMN operations TEXT NOT NULL DEFAULT 'extract_text'"
        )


def downgrade() -> None:
    bind = op.get_bind()
    mysql = bind.dialect.name == "mysql"
    if mysql:
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN provider")
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN operations")
    else:
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN provider")
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN operations")
