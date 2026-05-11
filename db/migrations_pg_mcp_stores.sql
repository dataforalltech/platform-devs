-- PostgreSQL migration for agent-twin-mcp and infra-mcp stores
-- Created: 2026-05-11
-- Schema: public (app database)

-- ============================================================================
-- agent-twin-mcp: agent_tokens table
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

-- Indexes for agent_tokens
CREATE INDEX IF NOT EXISTS idx_agent_tokens_prefix ON agent_tokens(token_prefix);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_user_id ON agent_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_active ON agent_tokens(active);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_tenant_id ON agent_tokens(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_expires_at ON agent_tokens(expires_at);

-- ============================================================================
-- infra-mcp: allocator tables
-- ============================================================================
CREATE TABLE IF NOT EXISTS vms (
    vm_id TEXT PRIMARY KEY,
    spec TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PROVISIONING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exclusive_locked_by TEXT,
    connection_hint TEXT
);

CREATE TABLE IF NOT EXISTS leases (
    lease_id TEXT PRIMARY KEY,
    vm_id TEXT NOT NULL REFERENCES vms(vm_id) ON DELETE CASCADE,
    spec TEXT NOT NULL,
    owner TEXT NOT NULL,
    purpose TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    exclusive BOOLEAN NOT NULL DEFAULT FALSE,
    priority TEXT NOT NULL DEFAULT 'low',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ,
    extension_count INTEGER NOT NULL DEFAULT 0,
    connection_hint TEXT
);

CREATE TABLE IF NOT EXISTS vm_keys (
    vm_id TEXT PRIMARY KEY REFERENCES vms(vm_id) ON DELETE CASCADE,
    encrypted_private_key BYTEA NOT NULL,
    public_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS queued_requests (
    request_id TEXT PRIMARY KEY,
    spec TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    owner TEXT NOT NULL,
    purpose TEXT,
    exclusive BOOLEAN NOT NULL DEFAULT FALSE,
    priority TEXT NOT NULL DEFAULT 'low',
    human_approved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'WAITING'
);

-- Indexes for leases and queued_requests
CREATE INDEX IF NOT EXISTS idx_leases_owner ON leases(owner);
CREATE INDEX IF NOT EXISTS idx_leases_vm_id ON leases(vm_id);
CREATE INDEX IF NOT EXISTS idx_leases_status ON leases(status);
CREATE INDEX IF NOT EXISTS idx_queued_status ON queued_requests(status, priority, created_at);
