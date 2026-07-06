"""create ml_vision_history table

Revision ID: 20260522_001
Revises:
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "20260522_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_vision_history",
        sa.Column("id", sa.String(64), nullable=False, primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False, server_default="detect_labels"),
        sa.Column("provider", sa.String(64), nullable=False, server_default="aws"),
        sa.Column("filename", sa.String(512), nullable=False, server_default=""),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="success"),
        sa.Column("started_at", sa.String(64), nullable=False, server_default=""),
        sa.Column("ended_at", sa.String(64), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(64), nullable=False, server_default=""),
        sa.Column("scope", sa.String(128), nullable=False, server_default="default"),
    )
    op.create_index("idx_vision_scope", "ml_vision_history", ["scope"])
    op.create_index("idx_vision_created_at", "ml_vision_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_vision_created_at", table_name="ml_vision_history")
    op.drop_index("idx_vision_scope", table_name="ml_vision_history")
    op.drop_table("ml_vision_history")
