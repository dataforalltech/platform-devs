"""Add connector_ids (per-operation) to ml_nlp_config.

Revision ID: 20260524_012
Revises: 20260524_011
Create Date: 2026-05-24

connector_ids is a JSON object mapping each operation to a connector ID,
enabling per-operation credential resolution in N:N configs.
Example: {"sentiment": "186", "entities": "188", "keywords": "187"}

If connector_ids is set it takes precedence over the legacy connector_id field.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260524_012"
down_revision: Union[str, None] = "20260524_011"
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
    if not _column_exists("ml_nlp_config", "connector_ids"):
        op.execute(sa.text(
            "ALTER TABLE ml_nlp_config ADD COLUMN connector_ids VARCHAR(1024) NULL "
            "COMMENT 'JSON: {operation -> connector_id} for per-operation credential resolution'"
        ))


def downgrade() -> None:
    if _column_exists("ml_nlp_config", "connector_ids"):
        op.execute(sa.text(
            "ALTER TABLE ml_nlp_config DROP COLUMN connector_ids"
        ))
