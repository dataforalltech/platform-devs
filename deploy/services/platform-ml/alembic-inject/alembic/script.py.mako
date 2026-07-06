"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

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
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}
${imports if imports else ""}

def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
