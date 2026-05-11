# Zilla Multi-Server Orchestration

## Overview

This document explains how to start, manage, and monitor all 10 Zilla MCPs simultaneously.

**Status**: ✅ Ready for parallel execution

---

## Quick Start

### 1. Ensure Dependencies Are Installed

```bash
pip install -r requirements-zillas.txt
```

### 2. Start All 10 Servers

```bash
./scripts/start_all_zillas.sh
```

**Output:**
```
🚀 Starting all 10 Zilla MCPs...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶️  Starting qazilla (port 7201)...
   PID: 12345 | Log: ~/.platform/logs/qazilla.log
▶️  Starting seczilla (port 7202)...
   ...
⏳ Waiting for servers to start...

✅ Validating servers...
✅ qazilla (port 7201) is healthy
✅ seczilla (port 7202) is healthy
...
🎉 All 10 Zillas started successfully!
```

---

## Zilla Port Map

| # | Name | Port | Service | Status |
|---|------|------|---------|--------|
| 1 | qazilla | 7201 | Quality Assurance | ✅ Python/FastAPI |
| 2 | seczilla | 7202 | Security & Threat Modeling | ✅ Python/FastAPI |
| 3 | archzilla | 7203 | Architecture & ADRs | ✅ Python/FastAPI |
| 4 | backzilla | 7204 | Backend APIs | ✅ Python/FastAPI |
| 5 | frontzilla | 7205 | Frontend Components | ✅ Python/FastAPI |
| 6 | opszilla | 7206 | Operations & DevOps | ✅ Python/FastAPI |
| 7 | pozilla | 7207 | Product Ownership | ✅ Python/FastAPI |
| 8 | productzilla | 7208 | Product Management | ✅ Python/FastAPI |
| 9 | cross-zilla-validators | 7209 | Cross-Zilla Validators | ✅ Python/FastAPI |
| 10 | zilla-observatory | 7210 | Monitoring & Dashboards | ✅ Python/FastAPI |

---

## Scripts

### Start All Servers

```bash
./scripts/start_all_zillas.sh
```

- Starts all 10 servers in parallel (background processes)
- Saves PIDs to `~/.platform/logs/{zilla}.pid`
- Logs output to `~/.platform/logs/{zilla}.log`
- Validates all servers respond to health checks

### Stop All Servers

```bash
./scripts/stop_all_zillas.sh
```

- Gracefully terminates all running Zillas
- Cleans up PID files
- Fallback: kills by process name if PID file missing

### Health Check

```bash
./scripts/health_check_zillas.sh
```

- Checks all 10 ports for connectivity
- Validates `/health` endpoint on each
- Reports percentage of healthy servers

**Output:**
```
🏥 Zilla Health Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ qazilla:7201 — Healthy
✅ seczilla:7202 — Healthy
...
Status: 10 / 10 healthy
🎉 All Zillas are healthy!
```

---

## Testing Individual Servers

### List Available Tools

```bash
curl -X POST http://localhost:7201/mcp/tools/list \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'
```

### Call a Tool (Example: qazilla create_test_plan)

```bash
curl -X POST http://localhost:7201/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "create_test_plan",
      "arguments": {
        "title": "My Test Plan",
        "feature": "Feature X",
        "scope": "Module Y",
        "objectives": "Validate Z"
      }
    }
  }'
```

---

## Logs

Each Zilla writes to `~/.platform/logs/{zilla}.log`:

```bash
tail -f ~/.platform/logs/qazilla.log
```

**Log format:**
```
[2026-05-11T12:34:56.123456] ✅ PostgreSQL connected
[2026-05-11T12:34:57.234567] INFO: Tool list_test_plans called
[2026-05-11T12:34:57.345678] Query succeeded: SELECT * FROM test_plans...
```

---

## Environment Variables

All Zillas use the same PostgreSQL connection:

```bash
export POSTGRES_HOST=claude-dev
export POSTGRES_PORT=5432
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres_password_local_dev
export POSTGRES_DB=app
```

---

## Load Testing

To validate concurrent connections:

```bash
# Install Apache Bench (if needed)
# apt-get install apache2-utils

# Run 100 requests with 10 concurrent:
ab -n 100 -c 10 http://localhost:7201/health
```

---

## Monitoring

### Process Status

```bash
ps aux | grep "_mcp.py" | grep -v grep
```

### Connection Status

```bash
netstat -tulnp | grep -E "7[2][0-9]{2}"
```

### PostgreSQL Connections

```bash
psql -h claude-dev -U postgres -d app -c \
  "SELECT client_addr, usename, query FROM pg_stat_activity WHERE query NOT LIKE '%pg_stat_activity%';"
```

---

## Troubleshooting

### Server won't start

1. Check port is not in use: `lsof -i :7201`
2. Check Python file exists: `ls -la qazilla-mcp-server/qazilla_mcp.py`
3. Check log: `tail -50 ~/.platform/logs/qazilla.log`

### Health check fails

1. Verify server is running: `ps aux | grep qazilla_mcp.py`
2. Check if port is listening: `curl http://localhost:7201/health`
3. Inspect PostgreSQL connection: `tail -20 ~/.platform/logs/qazilla.log | grep -i postgres`

### Database connection refused

1. Verify PostgreSQL is running: `psql -h claude-dev -U postgres -d app -c "SELECT 1"`
2. Check credentials match environment variables
3. Verify app database exists: `psql -h claude-dev -U postgres -l | grep app`

### Port already in use

Kill any previous instance:
```bash
pkill -f "_mcp.py"
./scripts/stop_all_zillas.sh
```

---

## Next Steps

1. **Load Testing** — Validate concurrent connections with Apache Bench or `wrk`
2. **CI/CD Integration** — Add Python builds to GitHub Actions
3. **Monitoring** — Set up log aggregation (ELK, Loki, Datadog)
4. **Health Checks** — Configure automated monitoring dashboard
5. **Production Deployment** — Containerize and deploy to Kubernetes

---

**Status**: ✅ Multi-server orchestration ready  
**Last Updated**: 2026-05-11  
**Python Version**: 3.10+  
**Framework**: FastAPI  
**Database**: PostgreSQL (primary only)
