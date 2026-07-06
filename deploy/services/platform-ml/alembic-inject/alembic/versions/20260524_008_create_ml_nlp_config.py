"""create ml_nlp_config table

Revision ID: 20260524_008
Revises: 20260521_003
Create Date: 2026-05-24

ml_nlp_config — stores NLP provider configuration presets per scope.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260524_008"
down_revision: Union[str, None] = "20260521_003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    if _is_mysql():
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_nlp_config (
                config_id       VARCHAR(64)   NOT NULL PRIMARY KEY,
                name            VARCHAR(255)  NOT NULL,
                description     TEXT          NULL,
                operation       VARCHAR(64)   NOT NULL COMMENT 'sentiment | entities | sentences | keywords',
                provider        VARCHAR(64)   NOT NULL COMMENT 'aws | azure | google | opensource',
                language        VARCHAR(16)   NOT NULL DEFAULT 'pt-BR',
                connector_id    VARCHAR(255)  NULL,
                tags            VARCHAR(512)  NULL,
                max_text_length INT           NULL,
                is_active       TINYINT(1)    NOT NULL DEFAULT 1,
                scope           VARCHAR(64)   NOT NULL DEFAULT 'default',
                created_by      VARCHAR(255)  NULL,
                created_at      VARCHAR(64)   NULL,
                updated_at      VARCHAR(64)   NULL,
                INDEX idx_ml_nlp_config_scope (scope, is_active)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS ml_nlp_config (
                config_id       TEXT          NOT NULL PRIMARY KEY,
                name            TEXT          NOT NULL,
                description     TEXT          NULL,
                operation       TEXT          NOT NULL,
                provider        TEXT          NOT NULL,
                language        TEXT          NOT NULL DEFAULT 'pt-BR',
                connector_id    TEXT          NULL,
                tags            TEXT          NULL,
                max_text_length INTEGER       NULL,
                is_active       INTEGER       NOT NULL DEFAULT 1,
                scope           VARCHAR(64)   NOT NULL DEFAULT 'default',
                created_by      TEXT          NULL,
                created_at      TEXT          NULL,
                updated_at      TEXT          NULL
            )
        """)
        op.execute("CREATE INDEX idx_ml_nlp_config_scope ON ml_nlp_config (scope, is_active)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_nlp_config")
