"""create ml_generative_jobs table

Revision ID: 20260617_001
Revises: 20260608_002
Create Date: 2026-06-17

Replaces the in-process _JOBS dict in generative/job_store.py with a shared
DB table so async video (and future image/banner) jobs are visible across all
replicas. Enables multi-instance deployments where POST hits replica A but
GET /jobs/{id} hits replica B.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "20260617_001"
down_revision: str | None = "20260608_002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    if _is_mysql():
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_generative_jobs (
                job_id      VARCHAR(64)   NOT NULL PRIMARY KEY,
                tenant_id   VARCHAR(64)   NOT NULL DEFAULT '',
                operation   VARCHAR(64)   NOT NULL,
                provider    VARCHAR(64)   NOT NULL DEFAULT '',
                status      VARCHAR(20)   NOT NULL DEFAULT 'queued',
                progress    INT           NOT NULL DEFAULT 0,
                step        VARCHAR(64)   NOT NULL DEFAULT 'queued',
                result      LONGTEXT      NULL,
                error       TEXT          NULL,
                created_at  VARCHAR(64)   NOT NULL,
                updated_at  VARCHAR(64)   NOT NULL,
                INDEX idx_gen_jobs_tenant (tenant_id, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
    else:
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_generative_jobs (
                job_id      TEXT          NOT NULL PRIMARY KEY,
                tenant_id   TEXT          NOT NULL DEFAULT '',
                operation   TEXT          NOT NULL,
                provider    TEXT          NOT NULL DEFAULT '',
                status      VARCHAR(20)   NOT NULL DEFAULT 'queued',
                progress    INTEGER       NOT NULL DEFAULT 0,
                step        TEXT          NOT NULL DEFAULT 'queued',
                result      TEXT          NULL,
                error       TEXT          NULL,
                created_at  TEXT          NOT NULL,
                updated_at  TEXT          NOT NULL
            )
        """))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS ml_generative_jobs"))
