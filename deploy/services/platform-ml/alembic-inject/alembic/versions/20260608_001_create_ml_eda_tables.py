"""create ml_eda tables (jobs, history, stages, runs)

Revision ID: 20260608_001
Revises: 20260606_001
Create Date: 2026-06-08

Canonical CONFIG/JOB/RUN/STAGE/HISTORY persistence for the EDA module, mirroring
the vision/nlp per-module schema (docs/ML_PROCESS_MODEL_CONTRACT.md). EDA jobs are
created when an exploratory analysis is requested (inline data from SQL Studio,
file upload, path or signed URL); stages track granular progress; runs capture the
logical execution outcome; history is the queryable audit trail.
"""

from __future__ import annotations

from alembic import op

revision = "20260608_001"
down_revision = "20260606_001"
branch_labels = None
depends_on = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    mysql = _is_mysql()

    # ── ml_eda_jobs ──────────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_jobs (
                job_id      VARCHAR(64)   PRIMARY KEY,
                run_id      VARCHAR(64)   NULL,
                status      VARCHAR(32)   NOT NULL DEFAULT 'queued',
                progress    INT           NOT NULL DEFAULT 0,
                step        VARCHAR(255)  NULL,
                source      VARCHAR(32)   NOT NULL DEFAULT 'inline',
                filename    VARCHAR(512)  NOT NULL DEFAULT '',
                n_rows      INT           NOT NULL DEFAULT 0,
                n_columns   INT           NOT NULL DEFAULT 0,
                result      LONGTEXT      NULL,
                error       TEXT          NULL,
                created_by  VARCHAR(255)  NOT NULL DEFAULT '',
                created_at  VARCHAR(64)   NOT NULL DEFAULT '',
                updated_at  VARCHAR(64)   NOT NULL DEFAULT '',
                started_at  VARCHAR(64)   NULL,
                ended_at    VARCHAR(64)   NULL,
                duration_ms INT           NOT NULL DEFAULT 0,
                scope       VARCHAR(128)  NOT NULL DEFAULT 'default',
                INDEX idx_eda_jobs_scope (scope, created_at),
                INDEX idx_eda_jobs_status (status, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_jobs (
                job_id      TEXT          PRIMARY KEY,
                run_id      TEXT,
                status      TEXT          NOT NULL DEFAULT 'queued',
                progress    INTEGER       NOT NULL DEFAULT 0,
                step        TEXT,
                source      TEXT          NOT NULL DEFAULT 'inline',
                filename    TEXT          NOT NULL DEFAULT '',
                n_rows      INTEGER       NOT NULL DEFAULT 0,
                n_columns   INTEGER       NOT NULL DEFAULT 0,
                result      JSONB,
                error       TEXT,
                created_by  TEXT          NOT NULL DEFAULT '',
                created_at  TEXT          NOT NULL DEFAULT '',
                updated_at  TEXT          NOT NULL DEFAULT '',
                started_at  TEXT,
                ended_at    TEXT,
                duration_ms INTEGER       NOT NULL DEFAULT 0,
                scope       VARCHAR(128)  NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_eda_jobs_scope ON ml_eda_jobs (scope, created_at)")
        op.execute("CREATE INDEX idx_eda_jobs_status ON ml_eda_jobs (status, created_at)")

    # ── ml_eda_history ───────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_history (
                id          VARCHAR(64)   PRIMARY KEY,
                source      VARCHAR(32)   NOT NULL DEFAULT 'inline',
                filename    VARCHAR(512)  NOT NULL DEFAULT '',
                n_rows      INT           NOT NULL DEFAULT 0,
                n_columns   INT           NOT NULL DEFAULT 0,
                result      LONGTEXT      NULL,
                status      VARCHAR(32)   NOT NULL DEFAULT 'success',
                started_at  VARCHAR(64)   NOT NULL DEFAULT '',
                ended_at    VARCHAR(64)   NOT NULL DEFAULT '',
                duration_ms INT           NOT NULL DEFAULT 0,
                error       TEXT          NULL,
                created_by  VARCHAR(256)  NOT NULL DEFAULT '',
                created_at  VARCHAR(64)   NOT NULL DEFAULT '',
                scope       VARCHAR(128)  NOT NULL DEFAULT 'default',
                INDEX idx_eda_history_scope (scope, created_at),
                INDEX idx_eda_history_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_history (
                id          TEXT          PRIMARY KEY,
                source      TEXT          NOT NULL DEFAULT 'inline',
                filename    TEXT          NOT NULL DEFAULT '',
                n_rows      INTEGER       NOT NULL DEFAULT 0,
                n_columns   INTEGER       NOT NULL DEFAULT 0,
                result      JSONB,
                status      TEXT          NOT NULL DEFAULT 'success',
                started_at  TEXT          NOT NULL DEFAULT '',
                ended_at    TEXT          NOT NULL DEFAULT '',
                duration_ms INTEGER       NOT NULL DEFAULT 0,
                error       TEXT,
                created_by  TEXT          NOT NULL DEFAULT '',
                created_at  TEXT          NOT NULL DEFAULT '',
                scope       VARCHAR(128)  NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_eda_history_scope ON ml_eda_history (scope, created_at)")
        op.execute("CREATE INDEX idx_eda_history_created ON ml_eda_history (created_at)")

    # ── ml_eda_stages ────────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_stages (
                id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
                job_id      VARCHAR(64)  NOT NULL,
                stage       VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'running',
                started_at  VARCHAR(64)  NOT NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INT          NULL,
                error       TEXT         NULL,
                INDEX idx_ml_eda_stages_job (job_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_stages (
                id          BIGSERIAL    PRIMARY KEY,
                job_id      VARCHAR(64)  NOT NULL,
                stage       VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'running',
                started_at  VARCHAR(64)  NOT NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INTEGER      NULL,
                error       TEXT         NULL
            )
        """)
        op.execute("CREATE INDEX idx_ml_eda_stages_job ON ml_eda_stages (job_id)")

    # ── ml_eda_runs ──────────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_runs (
                run_id            VARCHAR(64)  PRIMARY KEY,
                job_id            VARCHAR(64)  NOT NULL,
                status            VARCHAR(32)  NOT NULL DEFAULT 'completed',
                operation         VARCHAR(64)  NULL,
                provider          VARCHAR(64)  NULL,
                parameters        JSON         NULL,
                metrics           JSON         NULL,
                result            LONGTEXT     NULL,
                input_fingerprint VARCHAR(128) NULL,
                project_id        VARCHAR(64)  NULL,
                started_at        VARCHAR(64)  NULL,
                ended_at          VARCHAR(64)  NULL,
                duration_ms       INT          NULL,
                created_by        VARCHAR(255) NOT NULL DEFAULT '',
                created_at        VARCHAR(64)  NOT NULL DEFAULT '',
                scope             VARCHAR(64)  NOT NULL DEFAULT 'default',
                INDEX idx_ml_eda_runs_job (job_id),
                INDEX idx_ml_eda_runs_scope (scope, created_at DESC)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_eda_runs (
                run_id            VARCHAR(64)  PRIMARY KEY,
                job_id            VARCHAR(64)  NOT NULL,
                status            VARCHAR(32)  NOT NULL DEFAULT 'completed',
                operation         VARCHAR(64),
                provider          VARCHAR(64),
                parameters        JSONB,
                metrics           JSONB,
                result            JSONB,
                input_fingerprint VARCHAR(128),
                project_id        VARCHAR(64),
                started_at        VARCHAR(64),
                ended_at          VARCHAR(64),
                duration_ms       INTEGER,
                created_by        VARCHAR(255) NOT NULL DEFAULT '',
                created_at        VARCHAR(64)  NOT NULL DEFAULT '',
                scope             VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_eda_runs_job ON ml_eda_runs (job_id)")
        op.execute("CREATE INDEX idx_ml_eda_runs_scope ON ml_eda_runs (scope, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_eda_runs")
    op.execute("DROP TABLE IF EXISTS ml_eda_stages")
    op.execute("DROP TABLE IF EXISTS ml_eda_history")
    op.execute("DROP TABLE IF EXISTS ml_eda_jobs")
