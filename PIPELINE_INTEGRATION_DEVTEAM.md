# Pipeline Integration Plan — 8 DevTeam

**Purpose**: Register all 8 specialist DevTeam in the platform-devs pipeline for automated quality gates, promotions, and release management.

---

## Services Registration

### 1. Architecture (Architecture)
```
service: architecture
repo: platform-devs/architecture-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 2. Backend (Backend)
```
service: backend
repo: platform-devs/backend-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 3. Frontend-PixelFera (Frontend/Design)
```
service: frontend-pixelfera
repo: platform-devs/frontend-pixelfera-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 4. DevOps (DevOps/Infrastructure)
```
service: devops
repo: platform-devs/devops-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 5. Product-Owner (Project/Execution)
```
service: product-owner
repo: platform-devs/product-owner-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 6. Product-Manager (Product Strategy)
```
service: product-manager
repo: platform-devs/product-manager-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 7. QA-Engineer (Quality Assurance)
```
service: qa-engineer
repo: platform-devs/qa-engineer-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 8. Security (Security)
```
service: security
repo: platform-devs/security-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

---

## Quality Gates Configuration

### Environment: DEV (Automatic)
- **AutoMerge**: All gates pass → auto-merge to develop
- **Gates**: qa_tests, pr_approved (recommend all to pass)

### Environment: HML (Manual Approval Required)
- **Gates Required**:
  - `qa_tests` — Unit + integration tests pass
  - `pr_approved` — Code review approved
- **Trigger**: PR targeting release/* branch
- **Action**: Human approves promotion from dev → hml

### Environment: PROD (Manual Approval Required)
- **Gates Required**:
  - `qa_tests` — Comprehensive test coverage (>80%)
  - `security_scan` — No critical/high vulnerabilities
  - `pr_approved` — Code review approved
  - `health_check` — Service health endpoint responds
- **Trigger**: PR targeting v*.*.* tag or main branch
- **Action**: Human approves promotion from hml → prod

---

## Promotion Workflow

### 1. DEV (Automatic)
```
Feature branch → PR to develop
  ↓
GitHub: Check runs execute (CI, tests, lint, type-check)
  ↓
pipeline-mcp: Auto-evaluate qa_tests + pr_approved gates
  ↓
If all pass: Auto-merge to develop
If any fail: Block merge, report failures
```

### 2. HML (Manual, after DEV success)
```
develop (with latest feature) → Create release/vX.Y.Z branch
  ↓
Developer: Creates PR to release/vX.Y.Z
  ↓
pipeline-mcp: Runs quality gates (qa_tests, pr_approved)
  ↓
ReleaseMgr: Reviews + Approves in GitHub UI
  ↓
pipeline-mcp.approve_promotion(promotion_id) called
  ↓
Merge to hml environment, deploy to homolog
  ↓
devteam-observatory monitors hml health
```

### 3. PROD (Manual, after HML success)
```
release/vX.Y.Z (validated in hml) → Create PR to main (vX.Y.Z tag)
  ↓
pipeline-mcp: Runs all 4 gates (qa_tests, security_scan, pr_approved, health_check)
  ↓
Auditor/ReleaseMgr: Reviews + Approves in GitHub UI
  ↓
pipeline-mcp.approve_promotion(promotion_id) called
  ↓
Merge to main, create vX.Y.Z tag, deploy to prod
  ↓
devteam-observatory monitors prod health + sends alerts
```

---

## Gate Evaluation Logic

### qa_tests
**Evaluator**: QA-Engineer or pipeline-mcp calling qa-mcp  
**Pass Criteria**:
- Unit tests: 100% execution
- Integration tests: 100% execution
- Code coverage: ≥80% critical paths
- No failing tests

### security_scan
**Evaluator**: Security or pipeline-mcp calling qa-mcp  
**Pass Criteria**:
- SAST: No critical/high findings (or reviewed + accepted)
- Dependency scan: No unpatched critical/high CVEs
- Secrets scanning: No exposed credentials
- License compliance: No incompatible licenses

### pr_approved
**Evaluator**: Human code reviewer (via GitHub)  
**Pass Criteria**:
- Minimum 1 approval (configurable per org)
- No requested changes pending
- All conversations resolved

### health_check
**Evaluator**: pipeline-mcp querying service health endpoint  
**Pass Criteria**:
- HTTP 200 on `/health` or configured endpoint
- Response time < 2s
- All health checks in response: "healthy"

---

## Status Reporting

### Pipeline Overview
```
pipeline-mcp.get_pipeline_overview()
→ {
    total_services: 8,
    by_environment: { dev: 8, hml: 0, prod: 0 },
    blocked: 0,
    at_risk: 0,
    gates_failing: { qa_tests: 0, security_scan: 0, pr_approved: 0 }
  }
```

### Service Status (per DevTeam)
```
pipeline-mcp.get_pipeline(service="architecture")
→ {
    service: "architecture",
    current_env: "dev",
    blocked: false,
    last_promotion: { to_env: "dev", timestamp: "...", by: "..." },
    recent_gates: [
      { gate: "qa_tests", passed: true, evaluated_at: "..." },
      { gate: "pr_approved", passed: true, evaluated_at: "..." }
    ]
  }
```

### Promotion History
```
pipeline-mcp.get_promotion_history(service="architecture", limit=10)
→ [
    { id: 1, from: "dev", to: "hml", status: "approved", by: "releasemgr@..." },
    { id: 2, from: "hml", to: "prod", status: "waiting_approval", created_at: "..." }
  ]
```

---

## Integration with devteam-observatory

Observatory automatically monitors all 8 DevTeam:

### Metrics Collected
- **Cycle Time**: dev → hml → prod (per DevTeam)
- **Gate Pass Rate**: % of promotions passing each gate
- **Risk Heatmap**: At-risk DevTeam (blocked >5 days, low coverage)
- **Dependency Graph**: DevTeam → MCP service dependencies
- **Release Forecast**: ETA for next production release

### Alerts
- Gate failure → Slack notification to dev team
- Promotion blocked → Alert to ReleaseMgr
- Health check failure → Page on-call ops
- Release delay → Alert PM on schedule impact

---

## Rollback Procedure

### If Issue Detected in PROD
```
pipeline-mcp.rollback(
  service="architecture",
  env="prod",
  to_version="v1.2.3",
  reason="Critical bug in v1.2.4 found"
)
→ Roll back to v1.2.3 tag
→ Re-run health checks
→ Notify team via observatory alerts
→ Create incident report
```

---

## Implementation Roadmap

### Week 1: Setup
- [ ] Register all 8 DevTeam in pipeline-mcp
- [ ] Configure quality gates per environment
- [ ] Test gate evaluation logic

### Week 2: Integration
- [ ] Connect qa-mcp for qa_tests gate
- [ ] Connect Security for security_scan gate
- [ ] Setup health_check endpoints

### Week 3: Automation
- [ ] Enable auto-merge for dev promotions
- [ ] Setup GitHub Actions for gate triggers
- [ ] Configure Slack notifications

### Week 4: Monitoring
- [ ] Deploy devteam-observatory dashboards
- [ ] Setup alerting rules
- [ ] Create runbooks for common issues

---

## Command Reference

### Register Service
```bash
pipeline-mcp.register_pipeline(
  service="architecture",
  repo="platform-devs/architecture-mcp-server"
)
```

### Set Custom Gates
```bash
pipeline-mcp.set_pipeline_config(
  service="architecture",
  gates_required={
    "hml": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### Record Gate Result
```bash
pipeline-mcp.add_gate_result(
  service="architecture",
  env="hml",
  gate_type="qa_tests",
  passed=true,
  evaluated_by="qa-mcp",
  details="https://ci.example.com/run/12345"
)
```

### Promote Service
```bash
pipeline-mcp.promote_service(
  service="architecture",
  from_env="dev",
  to_env="hml",
  promoted_by="developer@example.com",
  reason="Release v1.3.0 ready for testing"
)
```

### Block Service
```bash
pipeline-mcp.block_service(
  service="architecture",
  reason="Waiting for security audit completion",
  blocked_by="auditor@example.com"
)
```

---

## Success Criteria

- [x] All 8 DevTeam registered in pipeline
- [ ] Quality gates configured and tested
- [ ] Promotion flow working (dev → hml → prod)
- [ ] Gate evaluations reporting correctly
- [ ] Observatory monitoring active
- [ ] Team trained on promotion workflow
- [ ] Runbooks documented

---

## References

- **pipeline-mcp**: `/home/dev/repos/platform-devs/shared/src/mcp-client.ts`
- **devteam-observatory**: `/home/dev/repos/platform-devs/devteam-observatory/`
- **qa-mcp**: Gate evaluation provider
- **Security**: Security gate provider
