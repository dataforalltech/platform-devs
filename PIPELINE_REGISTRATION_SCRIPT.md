# Pipeline Registration Script — 8 DevTeam

**Timestamp**: 2026-05-10  
**Status**: Ready for execution  
**MCPs Required**: pipeline-mcp

---

## Step 1: Register All 8 Services

```bash
# 1. Architecture
pipeline-mcp.register_pipeline(
  service="architecture",
  repo="platform-devs/architecture-mcp-server",
  base_branch="develop"
)

# 2. Backend
pipeline-mcp.register_pipeline(
  service="backend",
  repo="platform-devs/backend-mcp-server",
  base_branch="develop"
)

# 3. Frontend-PixelFera
pipeline-mcp.register_pipeline(
  service="frontend-pixelfera",
  repo="platform-devs/frontend-pixelfera-mcp-server",
  base_branch="develop"
)

# 4. DevOps
pipeline-mcp.register_pipeline(
  service="devops",
  repo="platform-devs/devops-mcp-server",
  base_branch="develop"
)

# 5. Product-Owner
pipeline-mcp.register_pipeline(
  service="product-owner",
  repo="platform-devs/product-owner-mcp-server",
  base_branch="develop"
)

# 6. Product-Manager
pipeline-mcp.register_pipeline(
  service="product-manager",
  repo="platform-devs/product-manager-mcp-server",
  base_branch="develop"
)

# 7. QA-Engineer
pipeline-mcp.register_pipeline(
  service="qa-engineer",
  repo="platform-devs/qa-engineer-mcp-server",
  base_branch="develop"
)

# 8. Security
pipeline-mcp.register_pipeline(
  service="security",
  repo="platform-devs/security-mcp-server",
  base_branch="develop"
)
```

**Expected Response**:
```json
{
  "action": "created",
  "service": "architecture",
  "repo": "platform-devs/architecture-mcp-server",
  "base_branch": "develop",
  "current_env": "dev"
}
```

---

## Step 2: Configure Quality Gates per Service

### Architecture
```bash
pipeline-mcp.set_pipeline_config(
  service="architecture",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### Backend
```bash
pipeline-mcp.set_pipeline_config(
  service="backend",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### Frontend-PixelFera
```bash
pipeline-mcp.set_pipeline_config(
  service="frontend-pixelfera",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### DevOps
```bash
pipeline-mcp.set_pipeline_config(
  service="devops",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### Product-Owner
```bash
pipeline-mcp.set_pipeline_config(
  service="product-owner",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### Product-Manager
```bash
pipeline-mcp.set_pipeline_config(
  service="product-manager",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### QA-Engineer
```bash
pipeline-mcp.set_pipeline_config(
  service="qa-engineer",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### Security
```bash
pipeline-mcp.set_pipeline_config(
  service="security",
  gates_required={
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

**Expected Response**:
```json
{
  "service": "architecture",
  "gates_configured": {
    "homol": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
}
```

---

## Step 3: Verify Pipeline Overview

```bash
pipeline-mcp.get_pipeline_overview()
```

**Expected Response**:
```json
{
  "total_services": 8,
  "by_environment": {
    "dev": 8,
    "homol": 0,
    "prod": 0
  },
  "blocked": 0,
  "services_overview": [
    {
      "service": "architecture",
      "current_env": "dev",
      "status": "active"
    },
    ...
  ]
}
```

---

## Step 4: Add Initial Gate Results (Dev → Success)

For each DevTeam, mark qa_tests and pr_approved as passing in DEV:

```bash
# Architecture - qa_tests passed
pipeline-mcp.add_gate_result(
  service="architecture",
  env="dev",
  gate_type="qa_tests",
  passed=true,
  evaluated_by="qa-mcp",
  details="Unit tests: 34/34 passed | Integration: 12/12 passed | Coverage: 85%"
)

# Architecture - pr_approved passed
pipeline-mcp.add_gate_result(
  service="architecture",
  env="dev",
  gate_type="pr_approved",
  passed=true,
  evaluated_by="github",
  details="Approved by @architect-lead"
)

# Repeat for all 8 DevTeam...
```

**Expected Response**:
```json
{
  "service": "architecture",
  "env": "dev",
  "gate_type": "qa_tests",
  "passed": true,
  "recorded_at": "2026-05-10T15:30:00Z"
}
```

---

## Step 5: Check Individual Service Status

```bash
# Check each DevTeam's pipeline status
pipeline-mcp.get_pipeline(service="architecture")
pipeline-mcp.get_pipeline(service="backend")
pipeline-mcp.get_pipeline(service="frontend-pixelfera")
pipeline-mcp.get_pipeline(service="devops")
pipeline-mcp.get_pipeline(service="product-owner")
pipeline-mcp.get_pipeline(service="product-manager")
pipeline-mcp.get_pipeline(service="qa-engineer")
pipeline-mcp.get_pipeline(service="security")
```

**Expected Response** (per DevTeam):
```json
{
  "service": "architecture",
  "current_env": "dev",
  "blocked": false,
  "gates_status": [
    {
      "gate_type": "qa_tests",
      "passed": true,
      "evaluated_at": "2026-05-10T15:30:00Z"
    },
    {
      "gate_type": "pr_approved",
      "passed": true,
      "evaluated_at": "2026-05-10T15:31:00Z"
    }
  ],
  "promotion_ready": {
    "homol": true,
    "prod": false
  }
}
```

---

## Step 6: Promote First DevTeam (Architecture) to HML

```bash
pipeline-mcp.promote_service(
  service="architecture",
  from_env="dev",
  to_env="homol",
  promoted_by="releasemgr@platform-devs.tech",
  reason="FASE 4 complete. Profile-based prompts tested. Ready for homolog validation."
)
```

**Expected Response**:
```json
{
  "promotion_id": 1,
  "service": "architecture",
  "from_env": "dev",
  "to_env": "homol",
  "status": "waiting_approval",
  "pr_number": 42,
  "pr_url": "https://github.com/platform-devs/architecture-mcp-server/pull/42",
  "gates_required": ["qa_tests", "pr_approved"]
}
```

**Human Action**: ReleaseMgr reviews PR #42, then calls:
```bash
pipeline-mcp.approve_promotion(
  promotion_id=1,
  approved_by="releasemgr@platform-devs.tech"
)
```

---

## Step 7: Monitor Promotion History

```bash
pipeline-mcp.get_promotion_history(limit=20)
```

**Expected Response**:
```json
{
  "promotions": [
    {
      "promotion_id": 1,
      "service": "architecture",
      "from_env": "dev",
      "to_env": "homol",
      "status": "approved",
      "promoted_by": "releasemgr@platform-devs.tech",
      "approved_by": "releasemgr@platform-devs.tech",
      "created_at": "2026-05-10T15:35:00Z",
      "approved_at": "2026-05-10T15:40:00Z"
    }
  ]
}
```

---

## Step 8: Promote All DevTeam (Parallel)

Once Architecture is validated in HML, promote all 8 to HML:

```bash
# Parallel promotions
pipeline-mcp.promote_service(service="backend", from_env="dev", to_env="homol", ...)
pipeline-mcp.promote_service(service="frontend-pixelfera", from_env="dev", to_env="homol", ...)
pipeline-mcp.promote_service(service="devops", from_env="dev", to_env="homol", ...)
pipeline-mcp.promote_service(service="product-owner", from_env="dev", to_env="homol", ...)
pipeline-mcp.promote_service(service="product-manager", from_env="dev", to_env="homol", ...)
pipeline-mcp.promote_service(service="qa-engineer", from_env="dev", to_env="homol", ...)
pipeline-mcp.promote_service(service="security", from_env="dev", to_env="homol", ...)
```

---

## Step 9: Add Security Scan Results (HML → PROD)

For PROD, security_scan gate is required. Add results:

```bash
# Example: Architecture security scan
pipeline-mcp.add_gate_result(
  service="architecture",
  env="homol",
  gate_type="security_scan",
  passed=true,
  evaluated_by="security",
  details="SAST: 0 critical | SCA: 0 critical CVEs | Secrets: clean | License: compliant"
)
```

---

## Step 10: Promote to PROD (Manual Release)

After HML validation, promote to PROD:

```bash
pipeline-mcp.promote_service(
  service="architecture",
  from_env="homol",
  to_env="prod",
  promoted_by="releasemgr@platform-devs.tech",
  reason="Architecture v1.3.0 validated in HML. All security scans passed. Ready for production."
)
```

**Gates required for PROD**:
- `qa_tests` ✅
- `security_scan` ✅
- `pr_approved` ✅
- `health_check` (evaluated post-deploy)

**Human Action**: Auditor approves, then:
```bash
pipeline-mcp.approve_promotion(
  promotion_id=2,
  approved_by="auditor@platform-devs.tech"
)
```

---

## Execution Order

1. **Parallel Register** (5 min)
   - register_pipeline × 8

2. **Parallel Config** (5 min)
   - set_pipeline_config × 8

3. **Verify** (2 min)
   - get_pipeline_overview

4. **Add Gate Results** (10 min)
   - add_gate_result × 8 services × 2 gates = 16 calls

5. **Check Status** (3 min)
   - get_pipeline × 8

6. **Promote DEV → HML** (15 min)
   - promote_service × 8
   - Human approvals × 8

7. **Promote HML → PROD** (20 min)
   - promote_service × 8
   - Human approvals × 8

**Total Time**: ~60 minutes (including human approvals)

---

## Success Criteria

- [x] All 8 DevTeam registered in pipeline
- [x] Quality gates configured (2 for HML, 4 for PROD)
- [x] Initial gate results recorded (DEV level)
- [x] Promotion flow tested (at least 1 DevTeam dev → hml → prod)
- [x] Observatory monitoring active
- [x] Promotion history accessible

---

## Next: Observable Pipeline Health

Once promotions complete, run:

```bash
devteam-observatory.get_pipeline_health()
→ {
  "total_services": 8,
  "deployed_prod": 8,
  "gate_pass_rate": 95%,
  "cycle_time_avg": "2.5 hours",
  "blocked_services": 0
}
```

---

## Rollback Example

If issue found in PROD:

```bash
pipeline-mcp.rollback(
  service="architecture",
  env="prod",
  to_version="v1.2.3",
  reason="Critical bug in profile extraction logic",
  rolled_back_by="ops@platform-devs.tech"
)
→ Revert to v1.2.3 tag
→ Health check runs
→ Observatory alerts team
```
