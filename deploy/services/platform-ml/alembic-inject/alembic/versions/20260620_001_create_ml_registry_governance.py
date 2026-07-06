"""create ml_promotion_policies and ml_model_cards tables

Revision ID: 20260620_001_registry_gov
Revises: 20260619_001_batch_jobs
Create Date: 2026-06-20

COMPLIANCE: registry governance state (promotion policies + model cards) MUST
persist in the per-tenant database, not in process memory / local files. These
two tables back MLPromotionPolicyStore / MLModelCardStore (db-per-tenant).
Timestamps are VARCHAR(64) ISO strings to match the canonical _now()/store pattern.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260620_001_registry_gov"
down_revision: Union[str, None] = "20260619_001_batch_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    if _is_mysql():
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_promotion_policies (
                model_name     VARCHAR(255) NOT NULL,
                scope          VARCHAR(64)  NOT NULL DEFAULT 'default',
                min_accuracy   DOUBLE       NULL,
                min_f1         DOUBLE       NULL,
                min_auc        DOUBLE       NULL,
                max_mape       DOUBLE       NULL,
                custom_metrics TEXT         NULL,
                created_at     VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at     VARCHAR(64)  NOT NULL DEFAULT '',
                PRIMARY KEY (model_name, scope)
            )
        """))
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_model_cards (
                model_name                  VARCHAR(255) NOT NULL,
                version                     VARCHAR(100) NOT NULL,
                scope                       VARCHAR(64)  NOT NULL DEFAULT 'default',
                intended_use                TEXT         NULL,
                limitations                 TEXT         NULL,
                training_data_description   TEXT         NULL,
                evaluation_data_description TEXT         NULL,
                primary_metric              VARCHAR(100) NULL,
                primary_metric_value        DOUBLE       NULL,
                fairness_notes              TEXT         NULL,
                contact_owner               VARCHAR(255) NULL,
                created_at                  VARCHAR(64)  NOT NULL DEFAULT '',
                updated_at                  VARCHAR(64)  NOT NULL DEFAULT '',
                PRIMARY KEY (model_name, version, scope)
            )
        """))
    else:
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_promotion_policies (
                model_name     TEXT NOT NULL,
                scope          VARCHAR(64) NOT NULL DEFAULT 'default',
                min_accuracy   DOUBLE PRECISION,
                min_f1         DOUBLE PRECISION,
                min_auc        DOUBLE PRECISION,
                max_mape       DOUBLE PRECISION,
                custom_metrics TEXT,
                created_at     TEXT NOT NULL DEFAULT '',
                updated_at     TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (model_name, scope)
            )
        """))
        op.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_model_cards (
                model_name                  TEXT NOT NULL,
                version                     VARCHAR(100) NOT NULL,
                scope                       VARCHAR(64) NOT NULL DEFAULT 'default',
                intended_use                TEXT,
                limitations                 TEXT,
                training_data_description   TEXT,
                evaluation_data_description TEXT,
                primary_metric              VARCHAR(100),
                primary_metric_value        DOUBLE PRECISION,
                fairness_notes              TEXT,
                contact_owner               VARCHAR(255),
                created_at                  TEXT NOT NULL DEFAULT '',
                updated_at                  TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (model_name, version, scope)
            )
        """))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS ml_model_cards"))
    op.execute(text("DROP TABLE IF EXISTS ml_promotion_policies"))
