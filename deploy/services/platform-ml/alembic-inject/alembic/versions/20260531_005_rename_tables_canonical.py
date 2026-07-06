"""rename file/audio tables to canonical names

Revision ID: 20260531_005
Revises: 20260531_004
Create Date: 2026-05-31

Canonical naming (docs/ML_PROCESS_MODEL_CONTRACT.md): ml_<module>_{config,jobs,history}.
Clean cut — no compatibility views. Readers must use the new names.

  ml_file_extractor        -> ml_file_config
  ml_file_extract_jobs     -> ml_file_jobs
  ml_file_extract_history  -> ml_file_history
  ml_audio_configs         -> ml_audio_config
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260531_005"
down_revision: Union[str, None] = "20260531_004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = [
    ("ml_file_extractor", "ml_file_config"),
    ("ml_file_extract_jobs", "ml_file_jobs"),
    ("ml_file_extract_history", "ml_file_history"),
    ("ml_audio_configs", "ml_audio_config"),
]


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        sql = (
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = :t"
        )
    else:
        sql = "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :t"
    row = bind.execute(text(sql), {"t": table}).fetchone()
    return bool(row and row[0])


def _rename(old: str, new: str) -> None:
    # Only rename when the old table exists and the new one does not yet.
    if not _table_exists(old) or _table_exists(new):
        return
    if _is_mysql():
        op.execute(f"RENAME TABLE {old} TO {new}")
    else:
        op.execute(f"ALTER TABLE {old} RENAME TO {new}")


def upgrade() -> None:
    for old, new in _RENAMES:
        _rename(old, new)


def downgrade() -> None:
    for old, new in _RENAMES:
        _rename(new, old)
