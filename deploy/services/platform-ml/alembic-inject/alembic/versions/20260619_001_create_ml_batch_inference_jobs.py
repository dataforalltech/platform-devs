"""create ml_batch_inference_jobs table

Revision ID: 20260619_001_batch_jobs
Revises: 20260618_db_registry
Create Date: 2026-06-19

Persiste batch inference jobs em DB para sobreviver restarts e suportar
múltiplos pods sem perda de estado (ML-INF-002).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260619_001_batch_jobs"
down_revision = "20260618_db_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if "ml_batch_inference_jobs" in insp.get_table_names():
        return  # idempotente

    op.create_table(
        "ml_batch_inference_jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total_records", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_records", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("result_path", sa.Text, nullable=True),
        sa.Column("predictions_json", sa.Text(length=16777215), nullable=True),  # MEDIUMTEXT
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.text("NOW()"), onupdate=sa.text("NOW()")),
        sa.Index("ix_batch_jobs_tenant_status", "tenant_id", "status"),
        sa.Index("ix_batch_jobs_tenant_created", "tenant_id", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("ml_batch_inference_jobs")
