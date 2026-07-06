"""create ml_training_templates table

Revision ID: 20260608_002
Revises: 20260608_001
Create Date: 2026-06-08

Saved, reusable training requests so an external scheduler can trigger recurring
training by template id (see platform-scheduler ml_* scheduling).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "20260608_002"
down_revision: str | None = "20260608_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    if _is_mysql():
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_training_templates (
                template_id  VARCHAR(64)  NOT NULL PRIMARY KEY,
                name         VARCHAR(255) NOT NULL,
                description  TEXT         NULL,
                family       VARCHAR(64)  NOT NULL,
                payload      LONGTEXT     NOT NULL,
                project_id   VARCHAR(64)  NULL,
                is_active    TINYINT(1)   NOT NULL DEFAULT 1,
                created_by   VARCHAR(255) NULL,
                created_at   VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at   VARCHAR(64)  NOT NULL DEFAULT '',
                scope        VARCHAR(64)  NOT NULL DEFAULT 'default',
                KEY ix_ml_training_templates_scope (scope, created_at)
            )
        """))
    else:
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_training_templates (
                template_id  TEXT NOT NULL PRIMARY KEY,
                name         TEXT NOT NULL,
                description  TEXT,
                family       VARCHAR(64) NOT NULL,
                payload      TEXT NOT NULL,
                project_id   TEXT,
                is_active    BOOLEAN NOT NULL DEFAULT TRUE,
                created_by   TEXT,
                created_at   TEXT NOT NULL DEFAULT '',
                updated_at   TEXT NOT NULL DEFAULT '',
                scope        VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """))
        op.execute(text(
            "CREATE INDEX idx_ml_training_templates_scope "
            "ON ml_training_templates (scope, created_at DESC)"
        ))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS ml_training_templates"))
