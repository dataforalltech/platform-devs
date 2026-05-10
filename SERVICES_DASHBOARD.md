# Services Dashboard

**Last Updated:** 2026-05-09T22:41:26Z  
**Overall Status:** 🔴 PRE-DEPLOYMENT (Services registered, containers not running)

---

## Executive Summary

**Total Services:** 23 registered in services-mcp
- **Healthy:** 1 (dataforall-ui-connect)
- **Unhealthy:** 0
- **Unknown/Stopped:** 22 (expected pre-deployment)

**Critical Actions:**
1. ✅ All 23 services registered in services-mcp registry
2. ⏳ Awaiting `docker-compose up -d` to start containers
3. 📋 See [SERVICES_REGISTRY_INVENTORY.md](SERVICES_REGISTRY_INVENTORY.md) for detailed port mapping

---

## Service Status Overview

### Infrastructure MCPs: Ports 7098-7109

```
┌─ INFRASTRUCTURE MCPS ─────────────────────────┐
│                                                │
│ 🔴 agent-twin-mcp      (7098)   ⚠️ unknown  │
│ 🔴 config-mcp          (7099)   ⚠️ unknown  │
│ 🔴 docs-mcp            (7100)   ⚠️ unknown  │
│ 🔴 session-mcp         (7101)   ⚠️ unknown  │
│ 🔴 services-mcp        (7102)   ⚠️ unknown  │
│ 🔴 deploy-mcp          (7103)   ⚠️ unknown  │
│ 🔴 qa-mcp              (7104)   ⚠️ unknown  │
│ 🔴 test-mcp            (7105)   ⚠️ unknown  │
│ 🔴 infra-mcp           (7106)   ⚠️ unknown  │
│ 🔴 pipeline-mcp        (7107)   ⚠️ unknown  │
│ 🔴 ai-governance-mcp   (7108)   ⚠️ unknown  │
│ 🔴 audit-mcp           (7109)   ⚠️ unknown  │
│                                                │
└────────────────────────────────────────────────┘
```

### Service MCPs: Ports 8001-8007

```
┌─ SERVICE MCPS ───────────────────────────────┐
│                                               │
│ 🔴 auth-mcp            (8001)   ⚠️ unknown  │
│ 🔴 admin-mcp           (8002)   ⚠️ unknown  │
│ 🔴 governance-mcp      (8003)   ⚠️ unknown  │
│ 🔴 scheduler-mcp       (8005)   ⚠️ unknown  │
│ 🔴 connectors-mcp      (8006)   ⚠️ unknown  │
│ 🔴 cache-mcp           (8007)   ⚠️ unknown  │
│                                               │
└───────────────────────────────────────────────┘
```

### REST APIs: Ports 8001-8006

```
┌─ REST APIS ───────────────────────────────────┐
│                                                │
│ 🔴 platform-auth       (8001)   ⚠️ unknown  │
│ 🔴 platform-admin      (8002)   ⚠️ unknown  │
│ 🔴 platform-governance (8003)   ⚠️ unknown  │
│ 🔴 platform-scheduler  (8005)   ⚠️ unknown  │
│ 🔴 platform-connectors (8006)   ⚠️ unknown  │
│                                                │
└────────────────────────────────────────────────┘
```

### Infrastructure Services (Not Phase 4c)

```
┌─ INFRASTRUCTURE SUPPORT ──────────────────────┐
│                                                │
│ 🔴 platform-postgres   (5432)   ⚠️ stopped  │
│ 🔴 platform-redis      (6379)   ⚠️ stopped  │
│ 🔴 platform-kafka      (9092)   ⚠️ stopped  │
│ 🟢 dataforall-ui       (8080)   ✅ running  │
│                                                │
└────────────────────────────────────────────────┘
```

---

## Detailed Service Status

### By Category

#### Infrastructure MCPs (12 services)
| # | Service | Port | Environment | Type | Status |
|---|---------|------|-------------|------|--------|
| 1 | agent-twin-mcp | 7098 | local | docker | ⚠️ unknown |
| 2 | config-mcp | 7099 | local | docker | ⚠️ unknown |
| 3 | docs-mcp | 7100 | local | docker | ⚠️ unknown |
| 4 | session-mcp | 7101 | local | docker | ⚠️ unknown |
| 5 | services-mcp | 7102 | local | docker | ⚠️ unknown |
| 6 | deploy-mcp | 7103 | local | docker | ⚠️ unknown |
| 7 | qa-mcp | 7104 | local | docker | ⚠️ unknown |
| 8 | test-mcp | 7105 | local | docker | ⚠️ unknown |
| 9 | infra-mcp | 7106 | local | docker | ⚠️ unknown |
| 10 | pipeline-mcp | 7107 | local | docker | ⚠️ unknown |
| 11 | ai-governance-mcp | 7108 | local | docker | ⚠️ unknown |
| 12 | audit-mcp | 7109 | local | docker | ⚠️ unknown |

#### Service MCPs (6 services)
| # | Service | Port | Environment | Type | Status |
|---|---------|------|-------------|------|--------|
| 1 | auth-mcp | 8001 | local | docker | ⚠️ unknown |
| 2 | admin-mcp | 8002 | local | docker | ⚠️ unknown |
| 3 | governance-mcp | 8003 | local | docker | ⚠️ unknown |
| 4 | scheduler-mcp | 8005 | local | docker | ⚠️ unknown |
| 5 | connectors-mcp | 8006 | local | docker | ⚠️ unknown |
| 6 | cache-mcp | 8007 | local | docker | ⚠️ unknown |

#### REST APIs (5 services)
| # | Service | Port | Environment | Type | Status |
|---|---------|------|-------------|------|--------|
| 1 | platform-auth | 8001 | local | docker | ⚠️ unknown |
| 2 | platform-admin | 8002 | local | docker | ⚠️ unknown |
| 3 | platform-governance | 8003 | local | docker | ⚠️ unknown |
| 4 | platform-scheduler | 8005 | local | docker | ⚠️ unknown |
| 5 | platform-connectors | 8006 | local | docker | ⚠️ unknown |

---

## Port Allocation Map

```
┌────────────────────────────────────┐
│  INFRASTRUCTURE MCPs                │
│  ────────────────────────────────   │
│  7098 → agent-twin-mcp              │
│  7099 → config-mcp                  │
│  7100 → docs-mcp                    │
│  7101 → session-mcp                 │
│  7102 → services-mcp                │
│  7103 → deploy-mcp                  │
│  7104 → qa-mcp                      │
│  7105 → test-mcp                    │
│  7106 → infra-mcp                   │
│  7107 → pipeline-mcp                │
│  7108 → ai-governance-mcp           │
│  7109 → audit-mcp                   │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│  SERVICE MCPS & REST APIS           │
│  ────────────────────────────────   │
│  8001 → auth-mcp / platform-auth    │
│  8002 → admin-mcp / platform-admin  │
│  8003 → governance-mcp / gov-api    │
│  8005 → scheduler-mcp / scheduler   │
│  8006 → connectors-mcp / connectors │
│  8007 → cache-mcp                   │
└────────────────────────────────────┘

┌────────────────────────────────────┐
│  INFRASTRUCTURE DATABASES           │
│  ────────────────────────────────   │
│  3306  → MySQL (platform-mysql)     │
│  5432  → PostgreSQL (platform-pg)   │
│  6379  → Redis (platform-redis)     │
│  9092  → Kafka (platform-kafka)     │
└────────────────────────────────────┘
```

---

## Health Check Details

### Last Full Health Check: 2026-05-09T22:41:26Z

**Command:** `mcp__services-mcp__check_all_health --timeout 5`

**Results:**
- Total Checked: 72 services (extended registry)
- Healthy: 1 ✅
- Unhealthy: 0
- Unknown/Not Running: 71 ⚠️

**Phase 4c Results (23 services):**
- All 23 Phase 4c services showing ⚠️ unknown status
- Expected behavior: containers not yet started
- Health check will show ✅ after `docker-compose up -d`

---

## Startup Checklist

Before deploying to production:

- [ ] Verify docker-compose.staging.yml syntax
  ```bash
  docker-compose -f docker-compose.staging.yml config
  ```

- [ ] Check port conflicts
  ```bash
  mcp__services-mcp__get_port_map
  ```

- [ ] Start the stack
  ```bash
  docker-compose -f docker-compose.staging.yml up -d
  ```

- [ ] Wait for services to be ready (5-30 seconds per service)
  ```bash
  docker-compose -f docker-compose.staging.yml ps
  ```

- [ ] Run health checks
  ```bash
  mcp__services-mcp__check_all_health --timeout 10
  ```

- [ ] Verify all Phase 4c services are healthy (✅)

---

## Quick Reference Commands

### List Services
```bash
# All local services
mcp__services-mcp__list_services --environment local

# Only MCPs
mcp__services-mcp__list_services --environment local --tag mcp

# Only REST APIs
mcp__services-mcp__list_services --environment local --tag rest-api
```

### Check Health
```bash
# All services
mcp__services-mcp__check_all_health --timeout 10

# Specific service
mcp__services-mcp__check_health --name agent-twin-mcp

# Get full status
mcp__services-mcp__service_status --name agent-twin-mcp
```

### Port Management
```bash
# Get all ports
mcp__services-mcp__get_port_map

# Find service by port
mcp__services-mcp__find_by_port --port 8001
```

---

## Related Documentation

- [SERVICES_REGISTRY_INVENTORY.md](SERVICES_REGISTRY_INVENTORY.md) - Detailed inventory with timestamps
- [docker-compose.staging.yml](/home/dev/repos/platform-devs/docker-compose.staging.yml) - Service definitions
- [MCP_REGISTRATION.md](MCP_REGISTRATION.md) - MCP server registration guide
- [STAGING_VALIDATION_RESULTS.md](STAGING_VALIDATION_RESULTS.md) - Docker Compose validation report

---

## Status Indicators

| Icon | Status | Meaning |
|------|--------|---------|
| 🟢 | ✅ healthy | Service running and responding correctly |
| 🟡 | ⚠️ degraded | Service running but with issues |
| 🔴 | ❌ unhealthy | Service failing or not responding |
| ⚪ | ⚠️ unknown | Service state unknown (not yet probed or not running) |

---

**Last Updated:** 2026-05-09T22:41:26Z  
**Next Update:** After docker-compose startup  
**Maintainer:** services-mcp registry agent

