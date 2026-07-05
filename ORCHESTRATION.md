# DevTeam Multi-Server Orchestration

## Overview

This document explains how to start, manage, and monitor all 10 DevTeam MCPs simultaneously.

**Status**: ✅ Ready for parallel execution

---

## Quick Start

### 1. Ensure Dependencies Are Installed

```bash
pip install -r requirements-devteam.txt
```

### 2. Start All 10 Servers

```bash
./scripts/start_all_devteam.sh
```

**Output:**
```
🚀 Starting all 10 DevTeam MCPs...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶️  Starting qa-engineer (port 7201)...
   PID: 12345 | Log: ~/.platform/logs/qa-engineer.log
▶️  Starting security (port 7202)...
   ...
⏳ Waiting for servers to start...

✅ Validating servers...
✅ qa-engineer (port 7201) is healthy
✅ security (port 7202) is healthy
...
🎉 All 10 DevTeam started successfully!
```

---

## DevTeam Port Map

| # | Name | Port | Service | Status |
|---|------|------|---------|--------|
| 1 | qa-engineer | 7201 | Quality Assurance | ✅ Python/FastAPI |
| 2 | security | 7202 | Security & Threat Modeling | ✅ Python/FastAPI |
| 3 | architecture | 7203 | Architecture & ADRs | ✅ Python/FastAPI |
| 4 | backend | 7204 | Backend APIs | ✅ Python/FastAPI |
| 5 | frontend | 7205 | Frontend Components | ✅ Python/FastAPI |
| 6 | devops | 7206 | Operations & DevOps | ✅ Python/FastAPI |
| 7 | product-owner | 7207 | Product Ownership | ✅ Python/FastAPI |
| 8 | product-manager | 7208 | Product Management | ✅ Python/FastAPI |
| 9 | cross-devteam-validators | 7209 | Cross-DevTeam Validators | ✅ Python/FastAPI |
| 10 | devteam-observatory | 7210 | Monitoring & Dashboards | ✅ Python/FastAPI |

---

## Scripts

### Start All Servers

```bash
./scripts/start_all_devteam.sh
```

- Starts all 10 servers in parallel (background processes)
- Saves PIDs to `~/.platform/logs/{devteam}.pid`
- Logs output to `~/.platform/logs/{devteam}.log`
- Validates all servers respond to health checks

### Stop All Servers

```bash
./scripts/stop_all_devteam.sh
```

- Gracefully terminates all running DevTeam
- Cleans up PID files
- Fallback: kills by process name if PID file missing

### Health Check

```bash
./scripts/health_check_devteam.sh
```

- Checks all 10 ports for connectivity
- Validates `/health` endpoint on each
- Reports percentage of healthy servers

**Output:**
```
🏥 DevTeam Health Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ qa-engineer:7201 — Healthy
✅ security:7202 — Healthy
...
Status: 10 / 10 healthy
🎉 All DevTeam are healthy!
```

---

## Testing Individual Servers

### List Available Tools

```bash
curl -X POST http://localhost:7201/mcp/tools/list \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'
```

### Call a Tool (Example: qa-engineer create_test_plan)

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

Each DevTeam writes to `~/.platform/logs/{devteam}.log`:

```bash
tail -f ~/.platform/logs/qa-engineer.log
```

**Log format:**
```
[2026-05-11T12:34:56.123456] ✅ PostgreSQL connected
[2026-05-11T12:34:57.234567] INFO: Tool list_test_plans called
[2026-05-11T12:34:57.345678] Query succeeded: SELECT * FROM test_plans...
```

---

## Environment Variables

All DevTeam use the same PostgreSQL connection:

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
2. Check Python file exists: `ls -la qa-engineer-mcp-server/qa-engineer_mcp.py`
3. Check log: `tail -50 ~/.platform/logs/qa-engineer.log`

### Health check fails

1. Verify server is running: `ps aux | grep qa-engineer_mcp.py`
2. Check if port is listening: `curl http://localhost:7201/health`
3. Inspect PostgreSQL connection: `tail -20 ~/.platform/logs/qa-engineer.log | grep -i postgres`

### Database connection refused

1. Verify PostgreSQL is running: `psql -h claude-dev -U postgres -d app -c "SELECT 1"`
2. Check credentials match environment variables
3. Verify app database exists: `psql -h claude-dev -U postgres -l | grep app`

### Port already in use

Kill any previous instance:
```bash
pkill -f "_mcp.py"
./scripts/stop_all_devteam.sh
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
