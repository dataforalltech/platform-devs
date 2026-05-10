# MCP Staging Validation Guide

**Version**: 1.0  
**Date**: May 9, 2026  
**Purpose**: Complete staging validation before production deployment  
**Status**: Ready for execution

---

## Quick Start (5 minutes)

### 1. Bring up staging environment

```bash
cd /home/dev/repos/platform-devs
docker-compose -f docker-compose.staging.yml up -d
```

### 2. Wait for all services to be healthy

```bash
# Check status
docker-compose -f docker-compose.staging.yml ps

# Wait for health checks (should see "healthy" status for all services)
# Typically takes 30-60 seconds
```

### 3. Run E2E integration tests

```bash
cd /home/dev/repos/platform-devs
python3 tests/e2e/staging-validation.py
```

Expected output: `OVERALL VERDICT: PASS`

### 4. Run load tests (optional, takes 10 minutes)

```bash
python3 tests/e2e/load-test.py
```

Expected output: `VERDICT: PASS`

### 5. Review results

Results are saved to:
- E2E Report: `/tmp/staging-e2e-test-report.json`
- Load Test Report: `/tmp/staging-load-test-report.json`

---

## Detailed Setup

### Prerequisites

- Docker & Docker Compose (v2.0+)
- Python 3.9+
- PostgreSQL client (psql) - optional
- Redis client (redis-cli) - optional
- 8GB RAM available
- 20GB disk space

### Step-by-Step Setup

#### 1. Clone and prepare environment

```bash
cd /home/dev/repos/platform-devs

# Ensure all MCP servers are built
ls -la docker-compose.staging.yml

# Verify .mcp.json has all 18 MCPs registered
cat .mcp.json | jq '.mcpServers | length'  # Should show 18
```

#### 2. Start infrastructure services

```bash
# Start just the databases and Kafka
docker-compose -f docker-compose.staging.yml up -d postgres redis zookeeper kafka

# Wait for Kafka to be healthy
docker-compose -f docker-compose.staging.yml logs kafka | grep "ready to serve requests"
```

#### 3. Start MCP servers (parallel)

```bash
# Start all MCPs at once
docker-compose -f docker-compose.staging.yml up -d \
  agent-twin-mcp config-mcp docs-mcp session-mcp services-mcp \
  deploy-mcp qa-mcp test-mcp infra-mcp pipeline-mcp \
  ai-governance-mcp audit-mcp

# Monitor startup
watch -n 1 'docker-compose -f docker-compose.staging.yml ps'
```

#### 4. Start REST APIs (depends on MCPs)

```bash
# Start all REST APIs
docker-compose -f docker-compose.staging.yml up -d \
  auth-api admin-api governance-api scheduler-api connectors-api

# Wait for all to be healthy
for i in {1..30}; do
  docker-compose -f docker-compose.staging.yml ps | grep healthy
  if [ $? -eq 0 ]; then echo "All healthy"; break; fi
  sleep 1
done
```

#### 5. Verify all services

```bash
# Check container status
docker-compose -f docker-compose.staging.yml ps

# Expected: All containers in "healthy" state

# Quick health check of all endpoints
curl -s http://localhost:7098/health | jq .  # agent-twin-mcp
curl -s http://localhost:8001/health | jq .  # auth-api
```

---

## Running E2E Integration Tests

### Basic Usage

```bash
cd /home/dev/repos/platform-devs
python3 tests/e2e/staging-validation.py
```

### What it Tests

1. **Health Checks** (all 23 services)
   - Verifies `/health` endpoint accessible on all MCPs + APIs
   - Expected: 23/23 healthy

2. **Agent Twin Authentication** (7098)
   - Creates test agent via agent-twin-mcp
   - Expected: 200 status, latency <100ms

3. **Auth API Login** (8001)
   - Attempts login via auth-api
   - Expected: 200 or 401 (auth response valid either way)

4. **Admin API Users** (8002)
   - Lists users via admin-api
   - Expected: 200 or 401/403 (endpoint responsive)

5. **Scheduler API Task** (8005)
   - Creates scheduled task via scheduler-api
   - Expected: 200, 201, or 401/403

6. **Config MCP Environment** (7099)
   - Retrieves environment config via config-mcp
   - Expected: 200 or 400 (both valid)

7. **Governance API Validate** (8003)
   - Validates decision via governance-api
   - Expected: 200, 400, 401, or 403

### Expected Results

```
OVERALL VERDICT: PASS
  ✓ P95 < 500ms: True (latency_ms)
  ✓ Success Rate ≥ 99%: True (success_rate_pct)
  ✓ Error Rate < 1%: True (error_rate_pct)
```

### Interpreting Results

| Verdict | Meaning | Next Action |
|---------|---------|------------|
| PASS | All checks passed, ready for load testing | Proceed to load tests |
| FAIL | One or more checks failed | Review error logs, fix issues |

### Troubleshooting

**Test timeout - "connection refused"**
```bash
# Ensure services are running
docker-compose -f docker-compose.staging.yml ps | grep healthy

# Check logs of failed service
docker-compose -f docker-compose.staging.yml logs auth-api
```

**Test failed - "HTTP 500"**
```bash
# Check service logs
docker-compose -f docker-compose.staging.yml logs [service-name]

# Verify database connectivity
docker-compose -f docker-compose.staging.yml exec postgres psql -U platform -d platform_staging -c "SELECT 1"
```

**Test timeout - "P95 > 500ms"**
```bash
# Check Docker resource constraints
docker stats

# If CPU/memory maxed, increase Docker limits
# Restart services with increased memory: docker-compose up -d
```

---

## Running Load Tests

### Basic Usage

```bash
cd /home/dev/repos/platform-devs
python3 tests/e2e/load-test.py
```

**⚠️ WARNING**: This test runs for 10 minutes with 100 concurrent agents. Ensure:
- At least 8GB RAM available
- No other processes consuming resources
- Staging environment fully healthy before starting

### Configuration

Current load test settings:
- **Duration**: 600 seconds (10 minutes)
- **Concurrent Agents**: 100
- **Throughput**: ~50 requests/second total
- **Endpoints**: 5 (auth, admin, scheduler, governance, config)

### What it Tests

Simulates realistic usage pattern:
- 100 concurrent agents making API calls
- 50 total requests/second distributed across agents
- 5 different endpoint types with random distribution
- Measures end-to-end latency including network + service processing

### Expected Results

```
VERDICT: PASS
  ✓ P95 < 500ms: True (latency_p95_ms)
  ✓ Success Rate ≥ 99%: True (success_rate_pct)
  ✓ Error Rate < 1%: True (error_rate_pct)
```

### Interpreting Results

| Metric | Target | Pass | Fail |
|--------|--------|------|------|
| Total Requests | N/A | 5000+ | <5000 |
| Success Rate | ≥99% | ≥99% | <99% |
| Error Rate | <1% | <1% | ≥1% |
| P95 Latency | <500ms | <500ms | ≥500ms |

### Resource Monitoring During Load Test

In separate terminal:

```bash
# Monitor Docker resource usage
watch -n 0.5 'docker stats --no-stream | grep staging'

# Expected: CPU 20-40%, Memory 3-5GB
```

### Troubleshooting

**Load test fails - "Connection refused"**
```bash
# Services may have crashed under load
docker-compose -f docker-compose.staging.yml ps

# Restart and try again with lower concurrency
# Edit load-test.py: change concurrent_agents = 50
```

**P95 Latency exceeds 500ms**
```bash
# Likely resource constraint - check Docker stats
docker stats

# If CPU maxed: reduce concurrent_agents in script
# If Memory maxed: increase Docker memory limit

# Typical targets per service:
# - auth-api: ~50ms avg
# - admin-api: ~40ms avg
# - scheduler-api: ~60ms avg
# - governance-api: ~45ms avg
# - config-mcp: ~30ms avg
```

---

## Health Check Endpoints

All 23 services expose `/health` endpoints:

### MCP Servers

```bash
for port in 7098 7099 7090 7100 7101 7102 7103 7104 7105 7106 7107 7108; do
  echo "Port $port:"
  curl -s http://localhost:$port/health | jq . || echo "FAILED"
done
```

### REST APIs

```bash
for port in 8001 8002 8003 8005 8006; do
  echo "Port $port:"
  curl -s http://localhost:$port/health | jq . || echo "FAILED"
done
```

### Expected Response

```json
{
  "status": "healthy",
  "timestamp": "2026-05-09T21:00:00Z",
  "version": "1.0"
}
```

---

## Viewing Results

### E2E Test Results

```bash
# View full report
cat /tmp/staging-e2e-test-report.json | jq .

# Extract key metrics
cat /tmp/staging-e2e-test-report.json | jq '.metrics | {success_rate_pct, error_rate_pct, latency_p95_ms}'

# View individual test results
cat /tmp/staging-e2e-test-report.json | jq '.tests[] | {test_name, status, latency_ms}'
```

### Load Test Results

```bash
# View full report
cat /tmp/staging-load-test-report.json | jq .

# Extract summary metrics
cat /tmp/staging-load-test-report.json | jq '.summary | {total_requests, success_rate_pct, latency_p95_ms, throughput_rps}'

# View error breakdown
cat /tmp/staging-load-test-report.json | jq '.summary.errors_by_type'
```

### Exporting Results for Sign-Off

```bash
# Copy reports to documentation
cp /tmp/staging-e2e-test-report.json /home/dev/repos/platform-service-template/docs/mcp/
cp /tmp/staging-load-test-report.json /home/dev/repos/platform-service-template/docs/mcp/

# Create summary for sign-off sheet
cat /tmp/staging-e2e-test-report.json | jq '.verdict' > /tmp/e2e-verdict.txt
cat /tmp/staging-load-test-report.json | jq '.summary.verdict' > /tmp/load-verdict.txt
```

---

## Cleaning Up Staging Environment

### Stop all services

```bash
cd /home/dev/repos/platform-devs
docker-compose -f docker-compose.staging.yml down
```

### Remove volumes (database data)

```bash
docker-compose -f docker-compose.staging.yml down -v
```

### Clean up logs and reports

```bash
rm /tmp/staging-*.json
docker system prune -a
```

---

## Next Steps After Validation

### If PASS

1. Update sign-off sheet with test results
2. Schedule executive review meetings
3. Gather architecture, security, and DevOps approvals
4. Begin production deployment planning

### If FAIL

1. Review error logs in detail
2. Identify root cause (infrastructure, config, or code issue)
3. Fix the issue
4. Restart staging environment from scratch
5. Re-run validation tests

---

## Production Readiness Checklist

Once staging validation is complete and passing, verify:

- [ ] E2E test verdict: **PASS**
- [ ] Load test verdict: **PASS**
- [ ] All 23 services report healthy
- [ ] Zero HIGH/CRITICAL security vulnerabilities
- [ ] Code coverage ≥80% for all services
- [ ] Runbooks documented and tested
- [ ] On-call escalation configured
- [ ] Backup/recovery procedures tested
- [ ] Incident response team trained

---

## Support & Escalation

**Issues during setup**: Contact DevOps team
**Test failures**: Check logs, update configuration
**Production questions**: Escalate to VP Engineering

---

## References

- MCP Architecture: `/docs/mcp/README.md`
- Production Runbook: `/docs/mcp/production-runbook.md`
- Sign-Off Sheet: `/docs/mcp/SIGN_OFF_SHEET.md`
- Incident Response: `/docs/mcp/incident-response.md`

---

**Last Updated**: May 9, 2026  
**Status**: Ready for staging validation  
**Approval Required**: Yes (VP Engineering sign-off)
