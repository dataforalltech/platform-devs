CREATE TABLE IF NOT EXISTS mcp_activity_ledger (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    roles JSONB NOT NULL,
    scopes JSONB NOT NULL,
    environment TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT NOT NULL,
    session_id TEXT,
    policy_decision_id TEXT,
    approval_ids JSONB NOT NULL,
    mcp TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,
    duration_ms INTEGER,
    status TEXT NOT NULL,
    client_ip TEXT,
    user_agent TEXT,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_mcp_activity_tenant_time
    ON mcp_activity_ledger (tenant_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_mcp_activity_correlation
    ON mcp_activity_ledger (correlation_id);

CREATE OR REPLACE FUNCTION reject_mcp_audit_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'mcp_activity_ledger is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS mcp_activity_ledger_append_only ON mcp_activity_ledger;
CREATE TRIGGER mcp_activity_ledger_append_only
BEFORE UPDATE OR DELETE ON mcp_activity_ledger
FOR EACH ROW EXECUTE FUNCTION reject_mcp_audit_mutation();

REVOKE UPDATE, DELETE, TRUNCATE ON mcp_activity_ledger FROM PUBLIC;
