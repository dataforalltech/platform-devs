# MCP Gateway — Quick Start Guide

## Overview

The MCP Gateway (port 8080) provides centralized access to all 26 MCPs with authentication, RBAC, rate limiting, and audit logging.

## Starting the Gateway

```bash
# Start PostgreSQL, Redis, and Gateway
docker compose -f docker-compose.staging.yml up -d postgres redis mcp-gateway

# Verify it's running
curl http://localhost:8080/health
```

## Test Tokens

Use these tokens in the `Authorization: Bearer <TOKEN>` header:

```bash
# Admin role (full access to all MCPs/tools)
TOKEN="test-admin-token"

# Developer role (limited access)
TOKEN="test-developer-token"

# Readonly role (status checks only)
TOKEN="test-readonly-token"
```

## Basic Usage

### List All MCPs
```bash
curl -H "Authorization: Bearer test-admin-token" \
  http://localhost:8080/mcp | jq .
```

### List Tools for an MCP
```bash
curl -H "Authorization: Bearer test-admin-token" \
  http://localhost:8080/mcp/qazilla-mcp/tools | jq .
```

### Call a Tool
```bash
curl -X POST \
  -H "Authorization: Bearer test-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"name": "generate_test_cases", "arguments": {"scenario": "login flow"}}' \
  http://localhost:8080/mcp/qazilla-mcp/tools/call | jq .
```

### Check Rate Limit Usage (Admin Only)
```bash
curl -H "Authorization: Bearer test-admin-token" \
  http://localhost:8080/admin/quotas | jq .
```

## Audit Logging

### Query Audit Logs
```bash
# Connect to staging PostgreSQL
psql -h localhost -p 5433 -U platform -d platform_staging -c \
  "SELECT ts, user_id, mcp, tool, status, duration_ms FROM mcp_audit_log ORDER BY ts DESC LIMIT 10;"
```

### Common Queries
```sql
-- Recent calls by user
SELECT user_id, COUNT(*) as calls, COUNT(CASE WHEN status='success' THEN 1 END) as successful
FROM mcp_audit_log
WHERE ts > NOW() - INTERVAL '1 hour'
GROUP BY user_id;

-- Errors in the last hour
SELECT ts, user_id, mcp, tool, result FROM mcp_audit_log
WHERE status='error' AND ts > NOW() - INTERVAL '1 hour'
ORDER BY ts DESC;

-- Rate limited requests
SELECT ts, user_id, mcp FROM mcp_audit_log
WHERE status='rate_limited'
ORDER BY ts DESC;
```

## RBAC Permissions

| Role | Access |
|------|--------|
| `admin` | All MCPs, all tools |
| `developer` | qazilla-mcp, backzilla-mcp (specific tools) |
| `readonly` | All MCPs, `status` tool only |

## Testing Rate Limiting & Audit Logging

```bash
# Run comprehensive test
python3 mcp-gateway/test_rate_limit_and_audit.py
```

This validates:
- ✅ Rate limiting infrastructure
- ✅ Audit logging to PostgreSQL
- ✅ RBAC blocking
- ✅ Database indices

## Performance Characteristics

- **Authentication**: <1ms (token lookup)
- **RBAC Check**: <1ms (in-memory dict)
- **Rate Limit Check**: ~1ms (Redis lookup)
- **Audit Log Write**: ~5-10ms (PostgreSQL async)
- **Tool Call Latency**: ~50-200ms (proxy + MCP execution)

## Troubleshooting

### Gateway not responding
```bash
# Check container logs
docker logs staging-mcp-gateway

# Verify database connection
docker exec staging-mcp-gateway python3 -c \
  "import psycopg2; conn = psycopg2.connect(host='postgres', user='platform', password='staging_password_123', database='platform_staging'); print('DB OK')"
```

### Rate limiter not working
```bash
# Check Redis connection
docker exec staging-redis redis-cli -a staging_redis_pass_123 ping

# Monitor rate limit keys
docker exec staging-redis redis-cli -a staging_redis_pass_123 KEYS "rate:*" | head -10
```

### Audit logs not appearing
```bash
# Check table exists
docker exec staging-postgres psql -U platform -d platform_staging -c "\dt mcp_audit_log;"

# Check indices
docker exec staging-postgres psql -U platform -d platform_staging -c "\di idx_audit*;"
```

## Common Errors

### 401 Unauthorized
- Token is missing or invalid
- Solution: Use Bearer token in Authorization header

### 403 Forbidden
- User role doesn't have permission for this tool
- Solution: Check RBAC_MAP in src/auth/rbac.py

### 429 Too Many Requests
- Rate limit exceeded (per-second or per-month)
- Solution: Wait for the time window to reset

### 503 Service Unavailable
- MCP server not accessible
- Solution: Ensure MCP is running and accessible at configured URL

## Next Steps

1. **Add Production Tokens**: Replace test tokens with bcrypt validation from agent-twin-mcp
2. **Enable Multi-tenancy**: Use tenant_id for data isolation
3. **Setup Monitoring**: Add Prometheus metrics and Grafana dashboards
4. **Configure HTTPS**: Add TLS for production deployment
5. **Implement Token Management UI**: Self-service token creation and revocation

---

For complete documentation, see `IMPLEMENTATION_STATUS.md`
