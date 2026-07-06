"""Add connector_id to ml_nlp_config.

Revision ID: 20260524_011
Revises: 20260524_010
Create Date: 2026-05-24

connector_id references a credential in platform-connectors.
Credentials for cloud providers (AWS, Azure, Google) are resolved
exclusively via ConnectorsClient — never from env vars or request body.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260524_011"
down_revision: Union[str, None] = "20260524_010"
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
    if not _column_exists("ml_nlp_config", "connector_id"):
        op.execute(sa.text(
            "ALTER TABLE ml_nlp_config ADD COLUMN connector_id VARCHAR(255) NULL"
        ))


def downgrade() -> None:
    if _column_exists("ml_nlp_config", "connector_id"):
        op.execute(sa.text(
            "ALTER TABLE ml_nlp_config DROP COLUMN connector_id"
        ))
