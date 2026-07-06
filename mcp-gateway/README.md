# MCP Gateway — Central Proxy for Multi-Tenant MCP Access

## Overview

The MCP Gateway provides centralized **authentication, authorization, rate limiting, and audit logging** for all MCPs in the platform.

```
Claude / Codex / Apps
    ↓
    ├─→ mcp-gateway:8080 (HTTP)
    │   ├─ Auth: Bearer token validation
    │   ├─ RBAC: Role-based access control
    │   ├─ Rate limit: Redis-backed throttling
    │   ├─ Audit: PostgreSQL logging
    │   └─ Proxy: Routes to internal MCPs (:7100)
    ↓
Internal MCPs (stdio + HTTP hybrid)
    ├─ qa-engineer-mcp:7100
    ├─ backend-mcp:7100
    ├─ infra-mcp:7100
    └─ ... (26+ MCPs total)
```

---

## Quick Start

### 1. Install Dependencies
```bash
cd mcp-gateway
pip install -e .
```

### 2. Set Environment Variables
```bash
export PG_HOST=localhost
export PG_PORT=5432
export PG_USER=postgres
export PG_PASSWORD=postgres
export PG_DB=platform_dev
export REDIS_URL=redis://localhost:6379
```

### 3. Start PostgreSQL & Redis (Docker)
```bash
docker compose -f ../docker-compose.staging.yml up -d postgres redis
```

### 4. Start Gateway
```bash
mcp-gateway
# Server runs on http://localhost:8080
```

---

## API Reference

### Health Check
```bash
GET /health
# {"status": "ok", "service": "mcp-gateway"}
```

### List Available MCPs
```bash
GET /mcp
# Returns list of {name, url, status}
```

### List Tools on an MCP
```bash
GET /mcp/{mcp_name}/tools
Headers:
  Authorization: Bearer <token>
```

### Call a Tool
```bash
POST /mcp/{mcp_name}/tools/call
Headers:
  Authorization: Bearer <token>
Body:
  {
    "name": "tool_name",
    "arguments": {...}
  }
```

### Admin: View Quotas
```bash
GET /admin/quotas
Headers:
  Authorization: Bearer <admin_token>
# Returns per-user monthly quota usage
```

---

## Authentication

Autenticação REAL (sem tokens de teste hardcoded). O gateway aceita duas formas,
tentadas nesta ordem: **JWT (produção)** → **static token (bootstrap)**. Sem token
válido → `403`. Ver `src/auth/token_validator.py`.

### Static tokens (bootstrap) — Bearer opaco com bcrypt

Gere um token opaco e seu hash bcrypt (guarde só o hash):
```bash
python -c "import bcrypt, secrets; \
raw = secrets.token_urlsafe(32); \
print('TOKEN =', raw); \
print('HASH  =', bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode())"
```

O `TOKEN` vai para o cliente (`Authorization: Bearer <TOKEN>`); o `HASH` vai para a
env `GATEWAY_STATIC_TOKENS_JSON` (equivalente à tabela `agent_tokens` do Postgres):
```bash
export GATEWAY_STATIC_TOKENS_JSON='[
  {
    "token_hash": "<hash bcrypt>",
    "user_id": "admin",
    "role": "admin",
    "scopes": ["*"],
    "tenant_id": "acme",
    "expires_at": null,
    "revoked": false
  }
]'
```
Também aceita a forma de mapa `{"<hash>": {"user_id": ..., "role": ..., ...}}`.
`expires_at` (epoch ou `null`) e `revoked` são respeitados na validação.

### JWT (produção) — OAuth 2.1 / RS256

Se o Bearer for um JWT (3 segmentos) e as envs abaixo estiverem setadas, o gateway
valida assinatura (JWKS ou PEM), `aud`, `iss` e `exp`:
```bash
export GATEWAY_AS_ISSUER="https://auth.suaempresa.com"     # claim iss esperado
export GATEWAY_RESOURCE="https://mcp.suaempresa.com"       # claim aud esperado
export GATEWAY_AS_JWKS_URL="https://auth.suaempresa.com/.well-known/jwks.json"
# alternativa ao JWKS (testes/sem HTTP): chave pública RSA em PEM
# export GATEWAY_AS_PUBLIC_KEY_PEM="-----BEGIN PUBLIC KEY----- ..."
# export GATEWAY_JWT_LEEWAY=30   # folga para exp/nbf (default 30s)
```
Claims mapeados: `sub`→`user_id`, `scope`→`scopes`, `role`, `tenant_id`.

---

## Authorization (RBAC)

Each role has scopes defining which MCPs and tools are accessible:

| Role | Scopes | Access |
|------|--------|--------|
| **admin** | `["*"]` | All MCPs, all tools |
| **developer** | `["qa-engineer-mcp", "backend-mcp", "architecture-mcp"]` | Quality & architecture tools |
| **data-scientist** | `["qa-engineer-mcp", "product-owner-mcp"]` | Testing & product analytics |
| **product-owner** | `["product-owner-mcp", "product-manager-mcp"]` | Product & requirements |
| **readonly** | `["*"]` (status only) | List operations only |

Enforcement:
```python
# Gateway checks authorization before proxying
if not is_authorized(user, mcp_name, tool_name):
    return HTTPException(403, "Not authorized")
```

---

## Rate Limiting

Tiered by role with **per-second** and **per-month** limits:

| Role | Per-Second | Per-Month |
|------|-----------|-----------|
| admin | 100 | 100,000 |
| developer | 20 | 10,000 |
| readonly | 5 | 1,000 |

Implementation: Redis keys with TTL
```python
# Per-second: key expires after 2 seconds
rate:user123:1725123456 → 12 calls

# Per-month: key expires after 30 days
quota:user123:2026-05 → 8,456 calls
```

Returns `429 Too Many Requests` when exceeded.

---

## Audit Logging

All tool calls are logged to PostgreSQL `mcp_audit_log` table:

```sql
CREATE TABLE mcp_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT NOW(),
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    tenant_id   TEXT,
    mcp         TEXT NOT NULL,
    tool        TEXT NOT NULL,
    arguments   JSONB,
    result      JSONB,
    duration_ms INTEGER,
    status      TEXT,              -- 'success' | 'error' | 'forbidden' | 'rate_limited'
    client_ip   TEXT,
    user_agent  TEXT
);

CREATE INDEX idx_audit_user_ts ON mcp_audit_log (user_id, ts);
CREATE INDEX idx_audit_mcp_tool_ts ON mcp_audit_log (mcp, tool, ts);
```

Query audit logs:
```sql
-- All calls by a user
SELECT * FROM mcp_audit_log 
WHERE user_id = 'dev1' 
ORDER BY ts DESC 
LIMIT 100;

-- Failed calls
SELECT * FROM mcp_audit_log 
WHERE status IN ('error', 'forbidden', 'rate_limited')
ORDER BY ts DESC;

-- Slowest calls
SELECT mcp, tool, AVG(duration_ms) as avg_ms 
FROM mcp_audit_log 
GROUP BY mcp, tool 
ORDER BY avg_ms DESC;
```

---

## Testing

### Unit Tests
```bash
pytest tests/test_gateway.py -v
```

### Integration Tests (requires PostgreSQL + Redis)
```bash
docker compose -f ../docker-compose.staging.yml up -d
pytest tests/ -v --cov=src
```

### Manual Testing

Os tokens de teste hardcoded foram **removidos**. Use um token real:

- **Static token (bootstrap):** gere um token opaco e seu hash bcrypt, coloque o hash em
  `GATEWAY_STATIC_TOKENS_JSON` e use o token cru no header. Gerar:
  ```bash
  python -c "import bcrypt, secrets; raw=secrets.token_urlsafe(32); print('TOKEN=', raw); print('HASH=', bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode())"
  ```
- **JWT (produção):** obtenha um access token do auth-mcp (Authorization Server) com `aud` =
  `GATEWAY_RESOURCE` e configure `GATEWAY_AS_ISSUER` + `GATEWAY_AS_JWKS_URL` no gateway.

```bash
export TOKEN=<seu-token-static-ou-jwt>

# Chamada autenticada
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/mcp/qa-engineer-mcp/tools

# Sem token → 403
curl http://localhost:8080/mcp/qa-engineer-mcp/tools

# Sem escopo/role para a ferramenta → 403 (RBAC)
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:8080/mcp/backend-mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "generate_service_layer", "arguments": {}}'
```

---

## Architecture

### Layer 1 — Gateway (This Service)
- **Port:** 8080 (HTTP)
- **Deps:** FastAPI, uvicorn, httpx, redis-py, psycopg2, bcrypt
- **Responsibilities:**
  - Token validation (bcrypt against PostgreSQL)
  - Role-based authorization (RBAC)
  - Rate limiting (Redis counters)
  - Audit logging (PostgreSQL inserts)
  - HTTP proxying (routes to MCPs)

### Layer 2 — MCPs (Hybrid Servers)
- **Port:** 7100 (HTTP) + stdio
- **Endpoints:**
  - `GET /health` — Health check
  - `GET /tools` — List available tools
  - `POST /tools/call` — Execute a tool
- **Access:** Only from gateway or for stdio (Claude)

### Layer 3 — Persistence
- **PostgreSQL:** agent_tokens (auth), mcp_audit_log (audit)
- **Redis:** rate limit counters (TTL per rule)

---

## Deployment

### Docker
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY mcp-gateway /app
RUN pip install -e .

EXPOSE 8080
CMD ["mcp-gateway"]
```

### Docker Compose
```yaml
services:
  mcp-gateway:
    build: ./mcp-gateway
    ports:
      - "8080:8080"
    environment:
      PG_HOST: postgres
      PG_PORT: 5432
      PG_USER: postgres
      PG_PASSWORD: ${PG_PASSWORD}
      PG_DB: platform_dev
      REDIS_URL: redis://redis:6379
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ${PG_PASSWORD}

  redis:
    image: redis:7
```

### Environment Variables (Production)
```bash
# PostgreSQL
PG_HOST=postgresql.internal
PG_PORT=5432
PG_USER=gateway_user
PG_PASSWORD=<secure_password>
PG_DB=platform_prod

# Redis
REDIS_URL=redis://redis-cluster:6379

# Optional
LOG_LEVEL=info
GATEWAY_TIMEOUT_SEC=30
```

---

## Troubleshooting

### "Failed to fetch tools" (503)
```
Cause: MCP server on port 7100 not responding
Fix:  - Check MCP is running: docker ps | grep 7100
      - Check MCP logs: docker logs <mcp_container>
      - Verify network: docker network ls
```

### "Rate limit exceeded" (429)
```
Cause: User exceeded per-second or per-month limit
Fix:  - Check Redis: redis-cli keys "rate:*"
      - Check quotas: GET /admin/quotas (admin only)
      - Increase limits in LIMITS dict (src/middleware/rate_limiter.py)
```

### "Unauthorized" (403)
```
Cause: Token invalid or user not authorized for tool
Fix:  - Verify token: GET /auth/validate -H "Authorization: Bearer <token>"
      - Check RBAC: is user's role allowed to access this MCP/tool?
      - Verify token not expired: SELECT * FROM agent_tokens WHERE token_hash = ...
```

### "Internal Error" (500)
```
Cause: Database or proxy error
Fix:  - Check PostgreSQL: psql -U postgres -c "SELECT 1"
      - Check Redis: redis-cli ping
      - Check MCP logs: docker logs <mcp_name>
      - Check gateway logs: docker logs mcp-gateway
```

---

## Compliance

- ✅ **RBAC:** Role-based access control per tool
- ✅ **Rate Limiting:** Tiered by role (admin/developer/readonly)
- ✅ **Audit Trail:** All tool calls logged to PostgreSQL
- ✅ **Token Security:** Bcrypt hashing, PostgreSQL storage
- ✅ **No Secrets:** All credentials environment-driven
- ✅ **Connection Pooling:** Thread-safe PostgreSQL + Redis connections

---

## Next Steps

1. **Deploy to Staging:** `docker compose -f docker-compose.staging.yml up`
2. **Run Tests:** `pytest tests/ -v`
3. **Monitor Audit Logs:** Query mcp_audit_log table for usage patterns
4. **Adjust Rate Limits:** Based on actual usage patterns
5. **Add Metrics:** Export Prometheus metrics for monitoring

See [COMPLIANCE_100_FINAL.md](../COMPLIANCE_100_FINAL.md) for full compliance verification.

