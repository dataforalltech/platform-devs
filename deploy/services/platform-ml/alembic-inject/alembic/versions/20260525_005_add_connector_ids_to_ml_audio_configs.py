"""Add connector_ids (per-operation) to ml_audio_configs.

Revision ID: 20260525_005
Revises: 20260524_012
Create Date: 2026-05-25

connector_ids is a JSON object mapping each audio operation to a connector ID,
enabling per-operation credential resolution in N:N configs.
Example: {"transcribe": "188", "synthesize": "190"}

If connector_ids is set for an operation it takes precedence over connector_id.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260525_005"
down_revision: Union[str, None] = "20260524_012"
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
    if not _column_exists("ml_audio_configs", "connector_ids"):
        op.execute(sa.text(
            "ALTER TABLE ml_audio_configs ADD COLUMN connector_ids TEXT NULL"
        ))


def downgrade() -> None:
    if _column_exists("ml_audio_configs", "connector_ids"):
        op.execute(sa.text(
            "ALTER TABLE ml_audio_configs DROP COLUMN connector_ids"
        ))
