-- Init schema for all Python MCP stores
-- Run once against platform_dev database

-- ============================================================================
-- agent-twin-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_tokens (
    id SERIAL PRIMARY KEY,
    token TEXT UNIQUE NOT NULL,
    token_prefix TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'developer',
    scopes JSONB NOT NULL DEFAULT '["*"]',
    environment TEXT NOT NULL DEFAULT 'dev',
    tenant_id TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_prefix    ON agent_tokens(token_prefix);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_user_id   ON agent_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_active    ON agent_tokens(active);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_tenant_id ON agent_tokens(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_expires   ON agent_tokens(expires_at);

-- ============================================================================
-- session-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS sessions (
    session_id           TEXT PRIMARY KEY,
    user_id              TEXT,
    repository_id        TEXT,
    title                TEXT,
    objective            TEXT,
    status               TEXT NOT NULL DEFAULT 'active',
    progress_percentage  INTEGER NOT NULL DEFAULT 0,
    last_checkpoint_summary TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sessions_status     ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_repo       ON sessions(repository_id);

CREATE TABLE IF NOT EXISTS checkpoints (
    id               SERIAL PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    summary          TEXT,
    context_snapshot JSONB,
    created_by_id    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id            SERIAL PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    content       TEXT,
    metadata      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);

CREATE TABLE IF NOT EXISTS tasks (
    id                    SERIAL PRIMARY KEY,
    session_id            TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    title                 TEXT NOT NULL,
    description           TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    needs_human_decision  BOOLEAN NOT NULL DEFAULT FALSE,
    progress_percentage   INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status);

CREATE TABLE IF NOT EXISTS suggestions (
    id                    SERIAL PRIMARY KEY,
    source_repository_id  TEXT,
    target_repository_id  TEXT,
    title                 TEXT NOT NULL,
    description           TEXT,
    kind                  TEXT NOT NULL DEFAULT 'improvement',
    priority              TEXT NOT NULL DEFAULT 'medium',
    status                TEXT NOT NULL DEFAULT 'pending',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- audit-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
    service     TEXT NOT NULL,
    repo        TEXT NOT NULL,
    env         TEXT NOT NULL,
    criticality TEXT,
    score       NUMERIC(5,2),
    passed      BOOLEAN,
    status      TEXT NOT NULL DEFAULT 'running',
    checklist   JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_service ON audit_log(service);
CREATE INDEX IF NOT EXISTS idx_audit_env     ON audit_log(env);
CREATE INDEX IF NOT EXISTS idx_audit_status  ON audit_log(status);

-- ============================================================================
-- docs-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id         SERIAL PRIMARY KEY,
    repo_path  TEXT NOT NULL,
    doc_type   TEXT NOT NULL,
    title      TEXT,
    content    JSONB,
    status     TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (repo_path, doc_type)
);
CREATE INDEX IF NOT EXISTS idx_documents_repo     ON documents(repo_path);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents(doc_type);

-- ============================================================================
-- infra-mcp (vms, leases, queued_requests, vm_keys)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vms (
    vm_id              TEXT PRIMARY KEY,
    spec               TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'PROVISIONING',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exclusive_locked_by TEXT,
    connection_hint    TEXT
);

CREATE TABLE IF NOT EXISTS leases (
    lease_id         TEXT PRIMARY KEY,
    vm_id            TEXT NOT NULL REFERENCES vms(vm_id) ON DELETE CASCADE,
    spec             TEXT NOT NULL,
    owner            TEXT NOT NULL,
    purpose          TEXT,
    status           TEXT NOT NULL DEFAULT 'PENDING',
    exclusive        BOOLEAN NOT NULL DEFAULT FALSE,
    priority         TEXT NOT NULL DEFAULT 'low',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ NOT NULL,
    released_at      TIMESTAMPTZ,
    extension_count  INTEGER NOT NULL DEFAULT 0,
    connection_hint  TEXT
);
CREATE INDEX IF NOT EXISTS idx_leases_owner  ON leases(owner);
CREATE INDEX IF NOT EXISTS idx_leases_vm_id  ON leases(vm_id);
CREATE INDEX IF NOT EXISTS idx_leases_status ON leases(status);

CREATE TABLE IF NOT EXISTS vm_keys (
    vm_id                TEXT PRIMARY KEY REFERENCES vms(vm_id) ON DELETE CASCADE,
    encrypted_private_key BYTEA NOT NULL,
    public_key           TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS queued_requests (
    request_id     TEXT PRIMARY KEY,
    spec           TEXT NOT NULL,
    duration_min   INTEGER NOT NULL,
    owner          TEXT NOT NULL,
    purpose        TEXT,
    exclusive      BOOLEAN NOT NULL DEFAULT FALSE,
    priority       TEXT NOT NULL DEFAULT 'low',
    human_approved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status         TEXT NOT NULL DEFAULT 'WAITING'
);
CREATE INDEX IF NOT EXISTS idx_queued_status ON queued_requests(status, priority, created_at);

-- ============================================================================
-- pipeline-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS pipelines (
    id           SERIAL PRIMARY KEY,
    service      TEXT UNIQUE NOT NULL,
    config       JSONB NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pipelines_service ON pipelines(service);
CREATE INDEX IF NOT EXISTS idx_pipelines_status  ON pipelines(status);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id           SERIAL PRIMARY KEY,
    pipeline_id  INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    run_id       TEXT UNIQUE NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    stages       JSONB NOT NULL DEFAULT '[]',
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    metadata     JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline ON pipeline_runs(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status   ON pipeline_runs(status);

-- ============================================================================
-- qa-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS test_runs (
    id          SERIAL PRIMARY KEY,
    service     TEXT NOT NULL,
    run_type    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    results     JSONB NOT NULL DEFAULT '{}',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    metadata    JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_test_runs_service ON test_runs(service);
CREATE INDEX IF NOT EXISTS idx_test_runs_status  ON test_runs(status);

-- ============================================================================
-- services-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS services (
    id           SERIAL PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,
    display_name TEXT,
    description  TEXT,
    status       TEXT NOT NULL DEFAULT 'unknown',
    port         INTEGER,
    host         TEXT DEFAULT 'localhost',
    health_url   TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}',
    tags         TEXT[] NOT NULL DEFAULT '{}',
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_services_status ON services(status);
CREATE INDEX IF NOT EXISTS idx_services_name   ON services(name);

-- ============================================================================
-- test-mcp
-- ============================================================================
CREATE TABLE IF NOT EXISTS test_plans (
    id         SERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    scope      TEXT,
    feature    TEXT,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS test_scenarios (
    id               SERIAL PRIMARY KEY,
    plan_id          INTEGER REFERENCES test_plans(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    category         TEXT,
    priority         TEXT NOT NULL DEFAULT 'medium',
    preconditions    TEXT,
    steps            TEXT,
    expected_result  TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_test_scenarios_plan ON test_scenarios(plan_id);

CREATE TABLE IF NOT EXISTS test_cases (
    id            SERIAL PRIMARY KEY,
    plan_id       INTEGER REFERENCES test_plans(id) ON DELETE CASCADE,
    scenario_id   INTEGER REFERENCES test_scenarios(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending',
    actual_result TEXT,
    notes         TEXT,
    evidence      TEXT,
    executed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_test_cases_plan     ON test_cases(plan_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_scenario ON test_cases(scenario_id);

CREATE TABLE IF NOT EXISTS quality_gates (
    id         SERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    type       TEXT NOT NULL,
    plan_id    INTEGER REFERENCES test_plans(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id           SERIAL PRIMARY KEY,
    checklist_id TEXT NOT NULL,
    order_num    INTEGER NOT NULL DEFAULT 0,
    description  TEXT NOT NULL,
    required     BOOLEAN NOT NULL DEFAULT TRUE,
    category     TEXT
);
CREATE INDEX IF NOT EXISTS idx_checklist_items_checklist ON checklist_items(checklist_id);

CREATE TABLE IF NOT EXISTS checklist_runs (
    id           TEXT PRIMARY KEY,
    checklist_id TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'in_progress',
    executor     TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS checklist_results (
    run_id   TEXT NOT NULL REFERENCES checklist_runs(id) ON DELETE CASCADE,
    item_id  INTEGER NOT NULL REFERENCES checklist_items(id) ON DELETE CASCADE,
    status   TEXT NOT NULL,
    notes    TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, item_id)
);

CREATE TABLE IF NOT EXISTS bug_reports (
    id          SERIAL PRIMARY KEY,
    plan_id     INTEGER REFERENCES test_plans(id) ON DELETE CASCADE,
    severity    TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    evidence    TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bug_reports_plan     ON bug_reports(plan_id);
CREATE INDEX IF NOT EXISTS idx_bug_reports_severity ON bug_reports(severity);

-- ============================================================================
-- ai-governance-mcp (stored in knowledge-base files, no Postgres tables needed)
-- ============================================================================
