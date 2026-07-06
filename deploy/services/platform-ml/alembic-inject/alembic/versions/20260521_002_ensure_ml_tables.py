"""ensure ml tables (idempotent catch-up)

Revision ID: 20260521_002
Revises: 001
Create Date: 2026-05-21

No-op catch-up revision. All tables are already created by 001 with
IF NOT EXISTS. This revision exists to align with deployments that were
stamped with 20260521_002 from a prior migration run.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260521_002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All tables created idempotently in revision 001 — nothing to do here.
    pass


def downgrade() -> None:
    pass
