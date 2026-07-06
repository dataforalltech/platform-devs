"""create ml_projects table and add project_id to ml_training_jobs and ml_runs

Revision ID: 20260529_005
Revises: 20260525_38c539394d14
Create Date: 2026-05-29

Creates ml_projects table.
Adds project_id column to ml_training_jobs (idempotent via information_schema).
Adds project_id column to ml_runs (idempotent via information_schema).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260529_005"
down_revision: Union[str, None] = "38c539394d14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _col_exists(bind, table: str, column: str) -> bool:
    """Check column existence via information_schema (MySQL/MariaDB)."""
    r = bind.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        f"AND table_name = '{table}' AND column_name = '{column}'"
    ))
    return bool((r.fetchone() or [0])[0])


def _table_exists_pg(bind, table: str) -> bool:
    r = bind.execute(text(
        f"SELECT to_regclass('{table}')"
    ))
    row = r.fetchone()
    return row is not None and row[0] is not None


def upgrade() -> None:
    mysql = _is_mysql()
    bind = op.get_bind()

    # ── ml_projects ───────────────────────────────────────────────────────────
    if mysql:
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_projects (
                project_id   VARCHAR(64)  NOT NULL PRIMARY KEY,
                name         VARCHAR(255) NOT NULL,
                description  TEXT         NULL,
                objective    VARCHAR(64)  NULL,
                tags         VARCHAR(512) NULL,
                is_active    TINYINT(1)   NOT NULL DEFAULT 1,
                created_by   VARCHAR(255) NULL,
                created_at   VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at   VARCHAR(64)  NOT NULL DEFAULT '',
                scope        VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """))
    else:
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_projects (
                project_id  TEXT NOT NULL PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT,
                objective   TEXT,
                tags        TEXT,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                created_by  TEXT,
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT '',
                scope       VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """))
        op.execute(text("CREATE INDEX idx_ml_projects_scope ON ml_projects (scope, created_at DESC)"))

    # ── ml_training_jobs.project_id ───────────────────────────────────────────
    if mysql:
        if not _col_exists(bind, "ml_training_jobs", "project_id"):
            op.execute(text(
                "ALTER TABLE ml_training_jobs ADD COLUMN project_id VARCHAR(64) NULL"
            ))
    else:
        op.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='ml_training_jobs' AND column_name='project_id'
                ) THEN
                    ALTER TABLE ml_training_jobs ADD COLUMN project_id TEXT NULL;
                END IF;
            END$$;
        """))

    # ── ml_runs.project_id ────────────────────────────────────────────────────
    if mysql:
        if not _col_exists(bind, "ml_runs", "project_id"):
            op.execute(text(
                "ALTER TABLE ml_runs ADD COLUMN project_id VARCHAR(64) NULL"
            ))
    else:
        op.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='ml_runs' AND column_name='project_id'
                ) THEN
                    ALTER TABLE ml_runs ADD COLUMN project_id TEXT NULL;
                END IF;
            END$$;
        """))


def downgrade() -> None:
    mysql = _is_mysql()
    bind = op.get_bind()

    if mysql:
        if _col_exists(bind, "ml_runs", "project_id"):
            op.execute(text("ALTER TABLE ml_runs DROP COLUMN project_id"))
        if _col_exists(bind, "ml_training_jobs", "project_id"):
            op.execute(text("ALTER TABLE ml_training_jobs DROP COLUMN project_id"))
    else:
        op.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='ml_runs' AND column_name='project_id')
                THEN ALTER TABLE ml_runs DROP COLUMN project_id; END IF;
            END$$;
        """))
        op.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='ml_training_jobs' AND column_name='project_id')
                THEN ALTER TABLE ml_training_jobs DROP COLUMN project_id; END IF;
            END$$;
        """))

    op.execute(text("DROP TABLE IF EXISTS ml_projects"))
