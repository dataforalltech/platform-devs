"""Migrate ml_nlp_config: add operation_providers, drop operation + provider columns.

Revision ID: 20260524_010
Revises: 20260524_008
Create Date: 2026-05-24

operation_providers is a JSON text column — e.g.:
  '{"sentiment": ["aws", "azure"], "keywords": ["d4all"]}'
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260524_010"
down_revision: Union[str, None] = "20260524_008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = '{column}'"
        )
    )
    row = result.fetchone()
    return bool(row and row[0] > 0)


def upgrade() -> None:
    # 1. Add operation_providers if missing
    if not _column_exists("ml_nlp_config", "operation_providers"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config ADD COLUMN operation_providers TEXT NULL"))

    # 2. Migrate existing rows: build JSON from old operation + provider columns
    if _column_exists("ml_nlp_config", "operation") and _column_exists("ml_nlp_config", "provider"):
        op.execute(sa.text(
            "UPDATE ml_nlp_config "
            "SET operation_providers = CONCAT('{\"', operation, '\": [\"', provider, '\"]}') "
            "WHERE operation_providers IS NULL AND operation != '' AND provider != ''"
        ))

    # 3. Drop old columns
    if _column_exists("ml_nlp_config", "operation"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config DROP COLUMN operation"))
    if _column_exists("ml_nlp_config", "provider"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config DROP COLUMN provider"))
    if _column_exists("ml_nlp_config", "connector_id"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config DROP COLUMN connector_id"))


def downgrade() -> None:
    if not _column_exists("ml_nlp_config", "operation"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config ADD COLUMN operation VARCHAR(64) NOT NULL DEFAULT ''"))
    if not _column_exists("ml_nlp_config", "provider"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config ADD COLUMN provider VARCHAR(64) NOT NULL DEFAULT ''"))
    if not _column_exists("ml_nlp_config", "connector_id"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config ADD COLUMN connector_id VARCHAR(255) NULL"))
    if _column_exists("ml_nlp_config", "operation_providers"):
        op.execute(sa.text("ALTER TABLE ml_nlp_config DROP COLUMN operation_providers"))
