"""Add operation_providers column to audio and file extractor configs.

Revision ID: 20260524_009
Revises: 20260524_004, 20260523_003
Create Date: 2026-05-24

"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic
revision = "20260524_009"
down_revision = "20260524_004"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check whether *column* exists in *table* via information_schema."""
    result = op.get_bind().execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        f"WHERE table_name = '{table}' AND column_name = '{column}'"
    ))
    row = result.fetchone()
    return bool(row and row[0] > 0)


def upgrade() -> None:
    # ── ml_audio_configs ──────────────────────────────────────────────────────
    if not _column_exists("ml_audio_configs", "operation_providers"):
        op.execute(
            "ALTER TABLE ml_audio_configs ADD COLUMN operation_providers TEXT"
        )
    if _column_exists("ml_audio_configs", "operation"):
        op.execute("ALTER TABLE ml_audio_configs DROP COLUMN operation")
    if _column_exists("ml_audio_configs", "provider"):
        op.execute("ALTER TABLE ml_audio_configs DROP COLUMN provider")
    if _column_exists("ml_audio_configs", "connector_id"):
        op.execute("ALTER TABLE ml_audio_configs DROP COLUMN connector_id")

    # ── ml_file_extractor ─────────────────────────────────────────────────────
    if not _column_exists("ml_file_extractor", "operation_providers"):
        op.execute(
            "ALTER TABLE ml_file_extractor ADD COLUMN operation_providers TEXT"
        )
    if _column_exists("ml_file_extractor", "provider"):
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN provider")
    if _column_exists("ml_file_extractor", "operations"):
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN operations")
    if _column_exists("ml_file_extractor", "connector_id"):
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN connector_id")


def downgrade() -> None:
    # ── ml_audio_configs ──────────────────────────────────────────────────────
    if not _column_exists("ml_audio_configs", "operation"):
        op.execute("ALTER TABLE ml_audio_configs ADD COLUMN operation TEXT NOT NULL DEFAULT ''")
    if not _column_exists("ml_audio_configs", "provider"):
        op.execute("ALTER TABLE ml_audio_configs ADD COLUMN provider TEXT NOT NULL DEFAULT ''")
    if not _column_exists("ml_audio_configs", "connector_id"):
        op.execute("ALTER TABLE ml_audio_configs ADD COLUMN connector_id TEXT")
    if _column_exists("ml_audio_configs", "operation_providers"):
        op.execute("ALTER TABLE ml_audio_configs DROP COLUMN operation_providers")

    # ── ml_file_extractor ─────────────────────────────────────────────────────
    if not _column_exists("ml_file_extractor", "provider"):
        op.execute("ALTER TABLE ml_file_extractor ADD COLUMN provider TEXT NOT NULL DEFAULT 'local'")
    if not _column_exists("ml_file_extractor", "operations"):
        op.execute("ALTER TABLE ml_file_extractor ADD COLUMN operations TEXT NOT NULL DEFAULT 'extract_text'")
    if not _column_exists("ml_file_extractor", "connector_id"):
        op.execute("ALTER TABLE ml_file_extractor ADD COLUMN connector_id TEXT")
    if _column_exists("ml_file_extractor", "operation_providers"):
        op.execute("ALTER TABLE ml_file_extractor DROP COLUMN operation_providers")
