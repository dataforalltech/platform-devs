"""merge all heads into single trunk

Revision ID: 38c539394d14
Revises: 20260524_006, 20260524_009, 20260524_012
Create Date: 2026-05-25 12:06:55.658687

Write pure SQL migrations using op.execute() — no SQLAlchemy types or DSL.

Example:
    def upgrade() -> None:
        op.execute(\"\"\"
            CREATE TABLE IF NOT EXISTS my_table (
                id   TEXT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                ...
            )
        \"\"\")

    def downgrade() -> None:
        op.execute("DROP TABLE IF EXISTS my_table")
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '38c539394d14'
down_revision: Union[str, None] = ('20260524_006', '20260524_009', '20260524_012')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
