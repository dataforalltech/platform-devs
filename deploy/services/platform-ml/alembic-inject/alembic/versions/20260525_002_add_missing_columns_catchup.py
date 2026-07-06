"""Add missing columns to ml_file_extractor, ml_vision_config

Revision ID: 20260525_002
Revises: 20260525_001
Create Date: 2026-05-25

Catch-up migration: adds columns that were added to schemas/repos but whose
migrations were never applied (either created in worktrees that weren't
merged or simply missing).

ml_file_extractor:
  - connector_id   VARCHAR(255) NULL
  - connector_ids  TEXT NULL

ml_vision_config:
  - connector_ids      TEXT NULL
  - operation_providers TEXT NULL
"""
from alembic import op
from sqlalchemy import text

revision = "20260525_002"
down_revision = "20260525_001"
branch_labels = None
depends_on = None


def _col(bind, table: str, column: str) -> bool:
    r = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        f"AND table_name = '{table}' AND column_name = '{column}'"
    ))
    return bool((r.fetchone() or [0])[0])


def upgrade() -> None:
    bind = op.get_bind()

    # ── ml_file_extractor ─────────────────────────────────────────────────────
    if not _col(bind, "ml_file_extractor", "connector_id"):
        op.execute(text(
            "ALTER TABLE ml_file_extractor "
            "ADD COLUMN connector_id VARCHAR(255) NULL"
        ))
    if not _col(bind, "ml_file_extractor", "connector_ids"):
        op.execute(text(
            "ALTER TABLE ml_file_extractor "
            "ADD COLUMN connector_ids TEXT NULL"
        ))

    # ── ml_vision_config ──────────────────────────────────────────────────────
    if not _col(bind, "ml_vision_config", "connector_ids"):
        op.execute(text(
            "ALTER TABLE ml_vision_config "
            "ADD COLUMN connector_ids TEXT NULL"
        ))
    if not _col(bind, "ml_vision_config", "operation_providers"):
        op.execute(text(
            "ALTER TABLE ml_vision_config "
            "ADD COLUMN operation_providers TEXT NULL"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    for table, col in [
        ("ml_file_extractor", "connector_ids"),
        ("ml_file_extractor", "connector_id"),
        ("ml_vision_config", "operation_providers"),
        ("ml_vision_config", "connector_ids"),
    ]:
        if _col(bind, table, col):
            op.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
