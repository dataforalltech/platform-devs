"""add model registry fields to ml_model_versions

Revision ID: 20260618_db_registry
Revises: 20260617_001
Create Date: 2026-06-18

Adiciona colunas necessárias para o DB-backed model registry que podem
estar faltando em ml_model_versions: stage, artifact_path, metadata_json,
tags, is_latest_production.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260618_db_registry"
down_revision = "20260617_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Verificar se colunas já existem antes de adicionar (idempotente)
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # Verifica se a tabela existe
    if "ml_model_versions" not in insp.get_table_names():
        op.create_table(
            "ml_model_versions",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("model_name", sa.String(255), nullable=False),
            sa.Column("version", sa.String(100), nullable=False),
            sa.Column("stage", sa.String(50), default="registered"),
            sa.Column("artifact_path", sa.Text, nullable=True),
            sa.Column("metadata_json", sa.Text, nullable=True),
            sa.Column("tags", sa.Text, nullable=True),
            sa.Column("tenant_id", sa.Integer, nullable=True),
            sa.Column("is_latest_production", sa.Boolean, default=False),
            sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()"), onupdate=sa.text("NOW()")),
            sa.UniqueConstraint("model_name", "version", "tenant_id", name="uq_model_version_tenant"),
        )
    else:
        # Adicionar colunas faltantes
        existing_cols = [c["name"] for c in insp.get_columns("ml_model_versions")]
        if "is_latest_production" not in existing_cols:
            op.add_column("ml_model_versions", sa.Column("is_latest_production", sa.Boolean, default=False))
        if "tags" not in existing_cols:
            op.add_column("ml_model_versions", sa.Column("tags", sa.Text, nullable=True))


def downgrade() -> None:
    pass  # Non-destructive: keep columns
