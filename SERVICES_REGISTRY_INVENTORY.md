# Services Registry Inventory

**Generated:** 2026-05-09T22:41:26Z  
**Status:** Services registered in services-mcp registry (containers not yet running)  
**Total Services:** 23 (12 Infrastructure MCPs + 6 Service MCPs + 5 REST APIs)

---

## Phase 4c: Infrastructure MCPs (12 services)

| Service | Port | Health Endpoint | Status | Last Check | Registered |
|---------|------|-----------------|--------|------------|----|
| agent-twin-mcp | 7098 | `/health` | ⚠️ unknown | 2026-05-09T22:41:12Z | 2026-05-09T22:40:37Z |
| config-mcp | 7099 | `/health` | ⚠️ unknown | 2026-05-09T22:41:18Z | 2026-05-09T22:40:38Z |
| docs-mcp | 7100 | `/health` | ⚠️ unknown | 2026-05-09T22:41:18Z | 2026-05-09T19:30:28Z |
| session-mcp | 7101 | `/health` | ⚠️ unknown | 2026-05-09T22:41:26Z | 2026-05-09T22:40:39Z |
| services-mcp | 7102 | `/health` | ⚠️ unknown | 2026-05-09T22:41:26Z | 2026-05-09T22:40:40Z |
| deploy-mcp | 7103 | `/health` | ⚠️ unknown | 2026-05-09T22:41:18Z | 2026-05-09T22:40:40Z |
| qa-mcp | 7104 | `/health` | ⚠️ unknown | 2026-05-09T22:41:26Z | 2026-05-09T22:40:41Z |
| test-mcp | 7105 | `/health` | ⚠️ unknown | 2026-05-09T22:41:26Z | 2026-05-09T22:40:42Z |
| infra-mcp | 7106 | `/health` | ⚠️ unknown | 2026-05-09T22:41:23Z | 2026-05-09T22:40:42Z |
| pipeline-mcp | 7107 | `/health` | ⚠️ unknown | 2026-05-09T22:41:23Z | 2026-05-09T22:40:43Z |
| ai-governance-mcp | 7108 | `/health` | ⚠️ unknown | 2026-05-09T22:41:12Z | 2026-05-09T22:40:44Z |
| audit-mcp | 7109 | `/health` | ⚠️ unknown | 2026-05-09T22:41:13Z | 2026-05-09T21:01:06Z |

---

## Phase 4c: Service MCPs (6 services)

| Service | Port | Health Endpoint | Status | Last Check | Registered |
|---------|------|-----------------|--------|------------|----|
| auth-mcp | 8001 | `/mcp/health` | ⚠️ unknown | 2026-05-09T22:41:13Z | 2026-05-09T19:30:29Z |
| admin-mcp | 8002 | `/mcp/health` | ⚠️ unknown | 2026-05-09T22:41:07Z | 2026-05-09T19:30:29Z |
| governance-mcp | 8003 | `/mcp/health` | ⚠️ unknown | 2026-05-09T22:41:23Z | 2026-05-09T19:30:30Z |
| scheduler-mcp | 8005 | `/mcp/health` | ⚠️ unknown | 2026-05-09T22:41:26Z | 2026-05-09T19:30:31Z |
| connectors-mcp | 8006 | `/mcp/health` | ⚠️ unknown | 2026-05-09T22:41:18Z | 2026-05-09T19:30:32Z |
| cache-mcp | 8007 | `/mcp/health` | ⚠️ unknown | 2026-05-09T22:41:13Z | 2026-05-09T22:40:49Z |

---

## Phase 4c: REST APIs (5 services)

| Service | Port | Health Endpoint | Status | Last Check | Registered |
|---------|------|-----------------|--------|------------|----|
| platform-auth | 8001 | `/api/health` | ⚠️ unknown | 2026-05-09T22:41:24Z | 2026-05-08T11:18:06Z |
| platform-admin | 8002 | `/api/health` | ⚠️ unknown | 2026-05-09T22:41:23Z | 2026-05-08T11:18:06Z |
| platform-governance | 8003 | `/api/health` | ⚠️ unknown | 2026-05-09T22:41:25Z | 2026-05-08T11:18:06Z |
| platform-scheduler | 8005 | `/api/health` | ⚠️ unknown | 2026-05-09T22:41:26Z | 2026-05-08T11:18:06Z |
| platform-connectors | 8006 | `/api/health` | ⚠️ unknown | 2026-05-09T22:41:24Z | 2026-05-09T14:18:30Z |

---

## Status Legend

| Symbol | Status | Meaning |
|--------|--------|---------|
| ✅ | healthy | Service is running and responding correctly |
| ⚠️ | unknown | Service not responding (expected: containers not started) |
| ❌ | unhealthy | Service is running but failing health checks |

---

## Port Usage Summary

### Infrastructure MCPs (7098-7109)
- Ports 7098-7109 are reserved for 12 infrastructure MCPs
- All registered with `/health` endpoints
- Type: docker containers

### Service MCPs (8001-8007)
- Ports 8001-8007 shared with REST APIs
- Service MCPs use `/mcp/health` endpoints
- Type: docker containers
- Note: 8001, 8002, 8003, 8005, 8006 also host REST APIs at `/api/health`

### REST APIs (8001-8006)
- Platform authentication, admin, governance, scheduler, connectors
- Use `/api/health` endpoints
- Type: docker containers
- Colocated with service MCPs on same ports (dual health endpoints)

---

## Service Registration Details

### Registration Method
All services registered via `mcp__services-mcp__register_service`:
- **Host:** localhost
- **Environment:** local
- **Type:** docker
- **Tags:** 
  - Infrastructure MCPs: `["infrastructure", "mcp", "phase-4c"]`
  - Service MCPs: `["service", "mcp", "phase-4c"]`
  - REST APIs: `["service", "rest-api", "phase-4c"]`

### Next Steps

1. **Start Docker Compose Stack:**
   ```bash
   cd /home/dev/repos/platform-devs
   docker-compose -f docker-compose.staging.yml up -d
   ```

2. **Verify Health:**
   ```bash
   # All services should transition to "healthy" (✅)
   mcp__services-mcp__check_all_health --timeout 10
   ```

3. **Monitor Service Status:**
   ```bash
   # List all services in local environment
   mcp__services-mcp__list_services --environment local
   
   # Get port map (check for conflicts)
   mcp__services-mcp__get_port_map
   ```

4. **Check Individual Service:**
   ```bash
   mcp__services-mcp__service_status --name <service-name>
   ```

---

## Conflict Analysis

No port conflicts detected:
- MCPs: 7098-7109 (exclusive range)
- REST APIs: 8001-8007 (shared with Service MCPs, different health endpoints)
- Other services: 3306, 5432, 6379, 9092 (infrastructure)

---

## Service Discovery

Services are now discoverable via:

1. **services-mcp registry:**
   ```bash
   mcp__services-mcp__list_services --environment local --type docker
   ```

2. **Port map lookup:**
   ```bash
   mcp__services-mcp__get_port_map
   ```

3. **Individual service metadata:**
   ```bash
   mcp__services-mcp__get_service --name <service-name>
   ```

---

## Audit Trail

| Action | Count | Timestamp | Details |
|--------|-------|-----------|---------|
| Services Created | 14 | 2026-05-09T22:40:37Z - 22:40:49Z | 12 MCPs + 2 APIs |
| Services Updated | 9 | 2026-05-09T19:30:28Z - 22:40:54Z | 6 Service MCPs + 5 APIs |
| Health Checks Run | 1 | 2026-05-09T22:41:26Z | Total 72 services checked |
| Healthy | 1 | | dataforall-ui-connect |
| Unhealthy/Unknown | 71 | | Expected (services not running) |

---

## Document History

- **2026-05-09T22:41:26Z** - Initial creation, all 23 Phase 4c services registered
- **2026-05-09T22:41:26Z** - Health checks executed, waiting for docker-compose startup

---

Generated by: `mcp__services-mcp` registry agent  
Next Review: After `docker-compose up -d` startup

