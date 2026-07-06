-- 0001_dev_plans.sql — Postgres DDL for the dev-agent Plan-Approve-Execute store.
--
-- REAL runtime dialect is PostgreSQL (asyncpg), NOT MySQL. Every status change is
-- driven by a GUARDED update in repository_pg.py (UPDATE ... WHERE status = ANY(...)),
-- which is what makes transitions idempotent / TOCTOU-safe (spec §6, critique §2.5).
--
-- Idempotent to apply: CREATE TABLE/INDEX IF NOT EXISTS so the contract-test PG
-- fixture can apply this repeatedly against a scratch database.

CREATE TABLE IF NOT EXISTS dev_plans (
    plan_id             VARCHAR(36)  PRIMARY KEY,
    session_id          VARCHAR(36)  NOT NULL,
    run_id              VARCHAR(36),
    question_id         VARCHAR(64)  NOT NULL UNIQUE,       -- 1:1 correlation with the poll
    runbook_id          VARCHAR(100) NOT NULL,
    runbook_version     VARCHAR(20)  NOT NULL,              -- versioned DAG origin
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending',
    title               VARCHAR(500) NOT NULL,
    summary             TEXT,
    responsible_profile VARCHAR(50),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dev_plans_session ON dev_plans (session_id);
CREATE INDEX IF NOT EXISTS idx_dev_plans_status  ON dev_plans (status);

CREATE TABLE IF NOT EXISTS dev_plan_items (
    item_id          VARCHAR(36)  PRIMARY KEY,
    plan_id          VARCHAR(36)  NOT NULL REFERENCES dev_plans (plan_id) ON DELETE CASCADE,
    sequence_num     INT          NOT NULL DEFAULT 0,
    runbook_id       VARCHAR(100) NOT NULL,
    task_id          VARCHAR(100) NOT NULL,
    depends_on       JSONB        NOT NULL DEFAULT '[]',
    tool             VARCHAR(200) NOT NULL,                 -- "<namespace>.<operationId>"
    capability       VARCHAR(10)  NOT NULL,                 -- read | write
    risk             VARCHAR(10)  NOT NULL DEFAULT 'low',
    required         BOOLEAN      NOT NULL DEFAULT TRUE,
    label            VARCHAR(500) NOT NULL,
    description      TEXT,
    responsible      VARCHAR(50)  NOT NULL,
    input_json       JSONB        NOT NULL DEFAULT '{}',
    idempotency_key  VARCHAR(64)  NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    output_json      JSONB,
    error_text       TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),   -- carimbo da última transição; TTL do reconcile
    UNIQUE (plan_id, task_id),                              -- one item per DAG task
    UNIQUE (idempotency_key)                                -- execution dedup
);
CREATE INDEX IF NOT EXISTS idx_dev_plan_items_plan   ON dev_plan_items (plan_id);
CREATE INDEX IF NOT EXISTS idx_dev_plan_items_status ON dev_plan_items (status);

CREATE TABLE IF NOT EXISTS dev_plan_approvals (
    approval_id         VARCHAR(36)  PRIMARY KEY,
    plan_id             VARCHAR(36)  NOT NULL REFERENCES dev_plans (plan_id) ON DELETE CASCADE,
    run_id              VARCHAR(36),
    approved_by         VARCHAR(100) NOT NULL,
    approved_item_ids   JSONB        NOT NULL,              -- persisted for real (not run_id=NULL stub)
    high_risk_confirmed JSONB        NOT NULL DEFAULT '[]',
    response_value      JSONB,
    approved_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dev_plan_approvals_plan ON dev_plan_approvals (plan_id);
