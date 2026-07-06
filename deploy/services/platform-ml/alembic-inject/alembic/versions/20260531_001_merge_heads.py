"""merge the two real ML heads into a single trunk

Revision ID: 20260531_001
Revises: 20260529_007, 20260529_009
Create Date: 2026-05-31

The ML migration graph had forked into two heads:
  - 20260529_007 (create ml_processing_stages)
  - 20260529_009 (add provider/operations to ml_file_extractor)

This no-op merge unifies them so ``alembic upgrade head`` resolves to a single
trunk for the canonical-process chain that follows (20260531_002..007).

CONTEXT (important): platform-ml and platform-connectors historically shared the
same database AND the same default ``alembic_version`` table, so the head you may
see in the DB (e.g. 20260530_0xx) can actually belong to platform-connectors.
This service now uses a dedicated ``version_table="alembic_version_ml"`` (see
alembic/env.py) so the two services no longer overwrite each other's revision.
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "20260531_001"
down_revision: Union[str, tuple[str, ...], None] = ("20260529_007", "20260529_009")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
