"""create ml_video tables (jobs, stages, runs)

Revision ID: 20260606_001
Revises: 20260531_007
Create Date: 2026-06-06

The video module is being promoted to the canonical process model
(docs/ML_PROCESS_MODEL_CONTRACT.md): async JOB + per-module STAGE + RUN, so the
frontend can show the same realtime progress banner used by nlp/files/audio.

  creates: ml_video_jobs, ml_video_stages, ml_video_runs

Schemas mirror ml_audio_jobs (20260531_002), the per-module stage table
(20260531_004) and the per-module run table (20260531_006) so the shared
ProcessingStageStore / ProcessingRunStore and VideoJobStore work unchanged.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260606_001"
down_revision: Union[str, None] = "20260531_007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def _create_jobs() -> None:
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_video_jobs (
                job_id      VARCHAR(64)  PRIMARY KEY,
                operation   VARCHAR(64)  NOT NULL DEFAULT 'transcribe',
                provider    VARCHAR(64)  NOT NULL DEFAULT 'faster_whisper',
                status      VARCHAR(32)  NOT NULL DEFAULT 'queued' COMMENT 'queued | running | completed | error | cancelled',
                progress    INT          NOT NULL DEFAULT 0,
                step        VARCHAR(255) NULL,
                input_ref   TEXT         NULL,
                output_path TEXT         NULL,
                transcript  LONGTEXT     NULL,
                language    VARCHAR(32)  NULL,
                model_size  VARCHAR(32)  NULL,
                segments    JSON         NULL,
                result      LONGTEXT     NULL,
                error       TEXT         NULL,
                run_id      VARCHAR(64)  NULL,
                created_by  VARCHAR(255) NOT NULL DEFAULT '',
                created_at  VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at  VARCHAR(64)  NOT NULL DEFAULT '',
                started_at  VARCHAR(64)  NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INT          NULL,
                input_size  INT          NULL,
                scope       VARCHAR(64)  NOT NULL DEFAULT 'default',
                INDEX idx_ml_video_jobs_scope (scope, created_at DESC),
                INDEX idx_ml_video_jobs_status (status, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_video_jobs (
                job_id      TEXT PRIMARY KEY,
                operation   TEXT NOT NULL DEFAULT 'transcribe',
                provider    TEXT NOT NULL DEFAULT 'faster_whisper',
                status      TEXT NOT NULL DEFAULT 'queued',
                progress    INTEGER NOT NULL DEFAULT 0,
                step        TEXT,
                input_ref   TEXT,
                output_path TEXT,
                transcript  TEXT,
                language    TEXT,
                model_size  TEXT,
                segments    JSONB,
                result      JSONB,
                error       TEXT,
                run_id      VARCHAR(64),
                created_by  TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL DEFAULT '',
                started_at  TEXT,
                ended_at    TEXT,
                duration_ms INTEGER,
                input_size  INTEGER,
                scope       VARCHAR(64) NOT NULL DEFAULT 'default'
            )
        """)
        op.execute("CREATE INDEX idx_ml_video_jobs_scope ON ml_video_jobs (scope, created_at DESC)")
        op.execute("CREATE INDEX idx_ml_video_jobs_status ON ml_video_jobs (status, created_at)")


def _create_stages() -> None:
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_video_stages (
                id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
                job_id      VARCHAR(64)  NOT NULL,
                stage       VARCHAR(64)  NOT NULL,
                status      VARCHAR(32)  NOT NULL DEFAULT 'running',
                started_at  VARCHAR(64)  NOT NULL,
                ended_at    VARCHAR(64)  NULL,
                duration_ms INT          NULL,
                error       TEXT         NULL,
                INDEX idx_ml_video_stages_job (job_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_video_stages (
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
        op.execute("CREATE INDEX idx_ml_video_stages_job ON ml_video_stages (job_id)")


def _create_runs() -> None:
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_video_runs (
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
                INDEX idx_ml_video_runs_job (job_id),
                INDEX idx_ml_video_runs_scope (scope, created_at DESC)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_video_runs (
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
        op.execute("CREATE INDEX idx_ml_video_runs_job ON ml_video_runs (job_id)")
        op.execute("CREATE INDEX idx_ml_video_runs_scope ON ml_video_runs (scope, created_at DESC)")


def upgrade() -> None:
    _create_jobs()
    _create_stages()
    _create_runs()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_video_runs")
    op.execute("DROP TABLE IF EXISTS ml_video_stages")
    op.execute("DROP TABLE IF EXISTS ml_video_jobs")
