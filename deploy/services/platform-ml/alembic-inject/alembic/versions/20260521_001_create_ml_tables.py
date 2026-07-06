"""create ml tables

Revision ID: 001
Revises:
Create Date: 2026-05-21

Creates all platform-ml metadata tables. Idempotent (IF NOT EXISTS).
Supports MySQL and PostgreSQL via dialect detection.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    mysql = _is_mysql()

    # ── ml_runs ───────────────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_runs (
                run_id              VARCHAR(64)  PRIMARY KEY,
                experiment_name     VARCHAR(255) NULL,
                status              VARCHAR(64)  NOT NULL,
                task                VARCHAR(128) NULL,
                algorithm           VARCHAR(128) NULL,
                model_name          VARCHAR(255) NULL,
                model_version       VARCHAR(128) NULL,
                dataset_fingerprint VARCHAR(128) NULL,
                started_at          VARCHAR(64)  NULL,
                ended_at            VARCHAR(64)  NULL,
                metrics             JSON         NOT NULL,
                parameters          JSON         NOT NULL,
                tags                JSON         NOT NULL,
                created_at          VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at          VARCHAR(64)  NOT NULL DEFAULT '',
                created_by          VARCHAR(255) NOT NULL DEFAULT '',
                updated_by          VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted          TINYINT(1)   NOT NULL DEFAULT 0,
                is_active           TINYINT(1)   NOT NULL DEFAULT 1,
                scope               VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_runs (
                run_id              TEXT PRIMARY KEY,
                experiment_name     TEXT,
                status              TEXT NOT NULL,
                task                TEXT,
                algorithm           TEXT,
                model_name          TEXT,
                model_version       TEXT,
                dataset_fingerprint TEXT,
                started_at          TEXT,
                ended_at            TEXT,
                metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
                parameters          JSONB NOT NULL DEFAULT '{}'::jsonb,
                tags                JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at          TEXT NOT NULL DEFAULT '',
                updated_at          TEXT NOT NULL DEFAULT '',
                created_by          TEXT NOT NULL DEFAULT '',
                updated_by          TEXT NOT NULL DEFAULT '',
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                is_active           BOOLEAN NOT NULL DEFAULT TRUE,
                scope               VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_runs_model ON ml_runs (model_name, model_version)")

    # ── ml_run_trials ─────────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_run_trials (
                trial_id         VARCHAR(64)  PRIMARY KEY,
                run_id           VARCHAR(64)  NOT NULL,
                trial_index      INT          NOT NULL,
                algorithm        VARCHAR(128) NOT NULL,
                status           VARCHAR(64)  NOT NULL,
                selection_metric VARCHAR(128) NULL,
                metric_value     DOUBLE       NULL,
                metrics          JSON         NOT NULL,
                parameters       JSON         NOT NULL,
                error            TEXT         NULL,
                created_at       VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at       VARCHAR(64)  NOT NULL DEFAULT '',
                created_by       VARCHAR(255) NOT NULL DEFAULT '',
                updated_by       VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted       TINYINT(1)   NOT NULL DEFAULT 0,
                is_active        TINYINT(1)   NOT NULL DEFAULT 1,
                scope            VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_run_trials (
                trial_id         TEXT PRIMARY KEY,
                run_id           TEXT NOT NULL,
                trial_index      INTEGER NOT NULL,
                algorithm        TEXT NOT NULL,
                status           TEXT NOT NULL,
                selection_metric TEXT,
                metric_value     DOUBLE PRECISION,
                metrics          JSONB NOT NULL DEFAULT '{}'::jsonb,
                parameters       JSONB NOT NULL DEFAULT '{}'::jsonb,
                error            TEXT,
                created_at       TEXT NOT NULL DEFAULT '',
                updated_at       TEXT NOT NULL DEFAULT '',
                created_by       TEXT NOT NULL DEFAULT '',
                updated_by       TEXT NOT NULL DEFAULT '',
                is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,
                is_active        BOOLEAN NOT NULL DEFAULT TRUE,
                scope            VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_trials_run ON ml_run_trials (run_id)")

    # ── ml_model_versions ─────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_model_versions (
                model_name     VARCHAR(255) NOT NULL,
                version        VARCHAR(128) NOT NULL,
                artifact_uri   TEXT         NULL,
                artifact_sha256 VARCHAR(128) NULL,
                stage          VARCHAR(64)  NOT NULL,
                registered_at  VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at     VARCHAR(64)  NOT NULL DEFAULT '',
                metrics        JSON         NOT NULL,
                parameters     JSON         NOT NULL,
                tags           JSON         NOT NULL,
                run_id         VARCHAR(64)  NULL,
                run_artifacts  JSON         NOT NULL,
                created_at     VARCHAR(64)  NOT NULL DEFAULT '',
                created_by     VARCHAR(255) NOT NULL DEFAULT '',
                updated_by     VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted     TINYINT(1)   NOT NULL DEFAULT 0,
                is_active      TINYINT(1)   NOT NULL DEFAULT 1,
                scope          VARCHAR(64)  NOT NULL DEFAULT 'default',
                PRIMARY KEY (model_name, version)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_model_versions (
                model_name      TEXT NOT NULL,
                version         TEXT NOT NULL,
                artifact_uri    TEXT,
                artifact_sha256 TEXT,
                stage           TEXT NOT NULL,
                registered_at   TEXT NOT NULL DEFAULT '',
                updated_at      TEXT NOT NULL DEFAULT '',
                metrics         JSONB NOT NULL DEFAULT '{}'::jsonb,
                parameters      JSONB NOT NULL DEFAULT '{}'::jsonb,
                tags            JSONB NOT NULL DEFAULT '{}'::jsonb,
                run_id          TEXT,
                run_artifacts   JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at      TEXT NOT NULL DEFAULT '',
                created_by      TEXT NOT NULL DEFAULT '',
                updated_by      TEXT NOT NULL DEFAULT '',
                is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                scope           VARCHAR(64) NOT NULL DEFAULT 'default',
                PRIMARY KEY (model_name, version)
            )
        """)

    # ── ml_artifacts ──────────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_artifacts (
                artifact_id    VARCHAR(64)  PRIMARY KEY,
                run_id         VARCHAR(64)  NOT NULL,
                model_name     VARCHAR(255) NULL,
                model_version  VARCHAR(128) NULL,
                artifact_type  VARCHAR(128) NOT NULL,
                uri            TEXT         NOT NULL,
                sha256         VARCHAR(128) NULL,
                metadata       JSON         NOT NULL,
                created_at     VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at     VARCHAR(64)  NOT NULL DEFAULT '',
                created_by     VARCHAR(255) NOT NULL DEFAULT '',
                updated_by     VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted     TINYINT(1)   NOT NULL DEFAULT 0,
                is_active      TINYINT(1)   NOT NULL DEFAULT 1,
                scope          VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_artifacts (
                artifact_id   TEXT PRIMARY KEY,
                run_id        TEXT NOT NULL,
                model_name    TEXT,
                model_version TEXT,
                artifact_type TEXT NOT NULL,
                uri           TEXT NOT NULL,
                sha256        TEXT,
                metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at    TEXT NOT NULL DEFAULT '',
                updated_at    TEXT NOT NULL DEFAULT '',
                created_by    TEXT NOT NULL DEFAULT '',
                updated_by    TEXT NOT NULL DEFAULT '',
                is_deleted    BOOLEAN NOT NULL DEFAULT FALSE,
                is_active     BOOLEAN NOT NULL DEFAULT TRUE,
                scope         VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_artifacts_run ON ml_artifacts (run_id)")

    # ── ml_audit_events ───────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audit_events (
                event_id    VARCHAR(64)  PRIMARY KEY,
                event_type  VARCHAR(128) NOT NULL,
                occurred_at VARCHAR(64)  NOT NULL,
                actor       VARCHAR(255) NOT NULL,
                model_name  VARCHAR(255) NULL,
                version     VARCHAR(128) NULL,
                run_id      VARCHAR(64)  NULL,
                details     JSON         NOT NULL,
                created_at  VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at  VARCHAR(64)  NOT NULL DEFAULT '',
                created_by  VARCHAR(255) NOT NULL DEFAULT '',
                updated_by  VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted  TINYINT(1)   NOT NULL DEFAULT 0,
                is_active   TINYINT(1)   NOT NULL DEFAULT 1,
                scope       VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audit_events (
                event_id    TEXT PRIMARY KEY,
                event_type  TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                actor       TEXT NOT NULL,
                model_name  TEXT,
                version     TEXT,
                run_id      TEXT,
                details     JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT '',
                created_by  TEXT NOT NULL DEFAULT '',
                updated_by  TEXT NOT NULL DEFAULT '',
                is_deleted  BOOLEAN NOT NULL DEFAULT FALSE,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                scope       VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_audit_model ON ml_audit_events (model_name, event_type)")

    # ── ml_training_jobs ──────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_training_jobs (
                job_id           VARCHAR(64)  PRIMARY KEY,
                family           VARCHAR(64)  NOT NULL,
                status           VARCHAR(64)  NOT NULL,
                actor            VARCHAR(255) NULL,
                created_at       VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at       VARCHAR(64)  NOT NULL DEFAULT '',
                started_at       VARCHAR(64)  NULL,
                ended_at         VARCHAR(64)  NULL,
                expires_at       VARCHAR(64)  NULL,
                timeout_seconds  INT          NULL,
                retry_count      INT          NOT NULL DEFAULT 0,
                max_retries      INT          NOT NULL DEFAULT 0,
                retry_of_job_id  VARCHAR(64)  NULL,
                request_payload  JSON         NOT NULL,
                result           JSON         NULL,
                error            TEXT         NULL,
                failure_reason   VARCHAR(128) NULL,
                model_name       VARCHAR(255) NULL,
                model_version    VARCHAR(128) NULL,
                run_id           VARCHAR(64)  NULL,
                created_by       VARCHAR(255) NOT NULL DEFAULT '',
                updated_by       VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted       TINYINT(1)   NOT NULL DEFAULT 0,
                is_active        TINYINT(1)   NOT NULL DEFAULT 1,
                scope            VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_training_jobs (
                job_id          TEXT PRIMARY KEY,
                family          TEXT NOT NULL,
                status          TEXT NOT NULL,
                actor           TEXT,
                created_at      TEXT NOT NULL DEFAULT '',
                updated_at      TEXT NOT NULL DEFAULT '',
                started_at      TEXT,
                ended_at        TEXT,
                expires_at      TEXT,
                timeout_seconds INTEGER,
                retry_count     INTEGER NOT NULL DEFAULT 0,
                max_retries     INTEGER NOT NULL DEFAULT 0,
                retry_of_job_id TEXT,
                request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                result          JSONB,
                error           TEXT,
                failure_reason  TEXT,
                model_name      TEXT,
                model_version   TEXT,
                run_id          TEXT,
                created_by      TEXT NOT NULL DEFAULT '',
                updated_by      TEXT NOT NULL DEFAULT '',
                is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                scope           VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_training_jobs_status ON ml_training_jobs (status, created_at)")

    # ── ml_endpoint_configs ───────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_endpoint_configs (
                model_name      VARCHAR(255) NOT NULL,
                tenant_id       VARCHAR(255) NOT NULL,
                enabled         TINYINT(1)   NOT NULL DEFAULT 1,
                auth_type       VARCHAR(64)  NOT NULL DEFAULT 'bearer',
                rate_limit_rpm  INT          NOT NULL DEFAULT 1000,
                timeout_seconds INT          NOT NULL DEFAULT 30,
                response_format VARCHAR(64)  NOT NULL DEFAULT 'json',
                created_at      VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at      VARCHAR(64)  NOT NULL DEFAULT '',
                created_by      VARCHAR(255) NOT NULL DEFAULT '',
                updated_by      VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted      TINYINT(1)   NOT NULL DEFAULT 0,
                is_active       TINYINT(1)   NOT NULL DEFAULT 1,
                scope           VARCHAR(64)  NOT NULL DEFAULT 'default',
                PRIMARY KEY (model_name, tenant_id)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_endpoint_configs (
                model_name      TEXT NOT NULL,
                tenant_id       TEXT NOT NULL,
                enabled         BOOLEAN NOT NULL DEFAULT TRUE,
                auth_type       TEXT NOT NULL DEFAULT 'bearer',
                rate_limit_rpm  INTEGER NOT NULL DEFAULT 1000,
                timeout_seconds INTEGER NOT NULL DEFAULT 30,
                response_format TEXT NOT NULL DEFAULT 'json',
                created_at      TEXT NOT NULL DEFAULT '',
                updated_at      TEXT NOT NULL DEFAULT '',
                created_by      TEXT NOT NULL DEFAULT '',
                updated_by      TEXT NOT NULL DEFAULT '',
                is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                scope           VARCHAR(64) NOT NULL DEFAULT 'default',
                PRIMARY KEY (model_name, tenant_id)
            )
        """)

    # ── ml_audio_history ──────────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audio_history (
                id         VARCHAR(64)  PRIMARY KEY,
                operation  VARCHAR(64)  NOT NULL,
                provider   VARCHAR(64)  NOT NULL,
                label      VARCHAR(255) NOT NULL,
                status     VARCHAR(64)  NOT NULL,
                voice_id   VARCHAR(255) NULL,
                details    JSON         NOT NULL,
                created_at VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at VARCHAR(64)  NOT NULL DEFAULT '',
                created_by VARCHAR(255) NOT NULL DEFAULT '',
                updated_by VARCHAR(255) NOT NULL DEFAULT '',
                is_deleted TINYINT(1)   NOT NULL DEFAULT 0,
                is_active  TINYINT(1)   NOT NULL DEFAULT 1,
                scope      VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_audio_history (
                id         TEXT PRIMARY KEY,
                operation  TEXT NOT NULL,
                provider   TEXT NOT NULL,
                label      TEXT NOT NULL,
                status     TEXT NOT NULL,
                voice_id   TEXT,
                details    JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                is_active  BOOLEAN NOT NULL DEFAULT TRUE,
                scope      VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)

    # ── ml_file_extract_history ───────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_file_extract_history (
                extract_id   VARCHAR(64)  PRIMARY KEY,
                file_name    VARCHAR(512) NOT NULL,
                file_type    VARCHAR(64)  NOT NULL,
                file_size    INT          NOT NULL DEFAULT 0,
                text_preview TEXT         NOT NULL,
                text_length  INT          NOT NULL DEFAULT 0,
                metadata     JSON         NOT NULL,
                request_id   VARCHAR(128) NULL,
                created_by   VARCHAR(255) NOT NULL DEFAULT '',
                created_at   VARCHAR(64)  NOT NULL DEFAULT '',
                scope        VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_file_extract_history (
                extract_id   TEXT PRIMARY KEY,
                file_name    TEXT NOT NULL,
                file_type    TEXT NOT NULL,
                file_size    INTEGER NOT NULL DEFAULT 0,
                text_preview TEXT NOT NULL DEFAULT '',
                text_length  INTEGER NOT NULL DEFAULT 0,
                metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
                request_id   TEXT,
                created_by   TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT '',
                scope        VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_file_extract_history_created ON ml_file_extract_history (created_at DESC)")
        op.execute("CREATE INDEX idx_ml_file_extract_history_scope ON ml_file_extract_history (scope, created_at DESC)")

    # ── ml_file_extract_jobs ──────────────────────────────────────────────────
    if mysql:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_file_extract_jobs (
                job_id     VARCHAR(64)  PRIMARY KEY,
                status     VARCHAR(32)  NOT NULL DEFAULT 'queued',
                progress   INT          NOT NULL DEFAULT 0,
                step       VARCHAR(255) NULL,
                file_name  VARCHAR(512) NOT NULL,
                file_type  VARCHAR(64)  NOT NULL,
                file_size  INT          NOT NULL DEFAULT 0,
                temp_path  TEXT         NULL,
                result     JSON         NULL,
                error      TEXT         NULL,
                created_by VARCHAR(255) NOT NULL DEFAULT '',
                created_at VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at VARCHAR(64)  NOT NULL DEFAULT '',
                started_at VARCHAR(64)  NULL,
                ended_at   VARCHAR(64)  NULL,
                scope      VARCHAR(64)  NOT NULL DEFAULT 'default'
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_file_extract_jobs (
                job_id     TEXT PRIMARY KEY,
                status     TEXT NOT NULL DEFAULT 'queued',
                progress   INTEGER NOT NULL DEFAULT 0,
                step       TEXT,
                file_name  TEXT NOT NULL,
                file_type  TEXT NOT NULL,
                file_size  INTEGER NOT NULL DEFAULT 0,
                temp_path  TEXT,
                result     JSONB,
                error      TEXT,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                ended_at   TEXT,
                scope      VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_file_extract_jobs_scope ON ml_file_extract_jobs (scope, created_at DESC)")
        op.execute("CREATE INDEX idx_ml_file_extract_jobs_status ON ml_file_extract_jobs (status, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_file_extract_jobs")
    op.execute("DROP TABLE IF EXISTS ml_file_extract_history")
    op.execute("DROP TABLE IF EXISTS ml_audio_history")
    op.execute("DROP TABLE IF EXISTS ml_endpoint_configs")
    op.execute("DROP TABLE IF EXISTS ml_training_jobs")
    op.execute("DROP TABLE IF EXISTS ml_audit_events")
    op.execute("DROP TABLE IF EXISTS ml_artifacts")
    op.execute("DROP TABLE IF EXISTS ml_model_versions")
    op.execute("DROP TABLE IF EXISTS ml_run_trials")
    op.execute("DROP TABLE IF EXISTS ml_runs")
