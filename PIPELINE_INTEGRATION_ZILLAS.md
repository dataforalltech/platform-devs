# Pipeline Integration Plan — 8 Zillas

**Purpose**: Register all 8 specialist Zillas in the platform-devs pipeline for automated quality gates, promotions, and release management.

---

## Services Registration

### 1. ArchZilla (Architecture)
```
service: archzilla
repo: platform-devs/archzilla-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 2. BackZilla (Backend)
```
service: backzilla
repo: platform-devs/backzilla-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 3. FrontZilla-PixelFera (Frontend/Design)
```
service: frontzilla-pixelfera
repo: platform-devs/frontzilla-pixelfera-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 4. OpsZilla (DevOps/Infrastructure)
```
service: opszilla
repo: platform-devs/opszilla-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 5. POZilla (Project/Execution)
```
service: pozilla
repo: platform-devs/pozilla-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 6. ProductZilla (Product Strategy)
```
service: productzilla
repo: platform-devs/productzilla-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 7. QAZilla (Quality Assurance)
```
service: qazilla
repo: platform-devs/qazilla-mcp-server
base_branch: develop
gates_hml: [qa_tests, pr_approved]
gates_prod: [qa_tests, security_scan, pr_approved, health_check]
```

### 8. SecZilla (Security)
```
service: seczilla
repo: platform-devs/seczilla-mcp-server
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
zilla-observatory monitors hml health
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
zilla-observatory monitors prod health + sends alerts
```

---

## Gate Evaluation Logic

### qa_tests
**Evaluator**: QAZilla or pipeline-mcp calling qa-mcp  
**Pass Criteria**:
- Unit tests: 100% execution
- Integration tests: 100% execution
- Code coverage: ≥80% critical paths
- No failing tests

### security_scan
**Evaluator**: SecZilla or pipeline-mcp calling qa-mcp  
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

### Service Status (per Zilla)
```
pipeline-mcp.get_pipeline(service="archzilla")
→ {
    service: "archzilla",
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
pipeline-mcp.get_promotion_history(service="archzilla", limit=10)
→ [
    { id: 1, from: "dev", to: "hml", status: "approved", by: "releasemgr@..." },
    { id: 2, from: "hml", to: "prod", status: "waiting_approval", created_at: "..." }
  ]
```

---

## Integration with zilla-observatory

Observatory automatically monitors all 8 Zillas:

### Metrics Collected
- **Cycle Time**: dev → hml → prod (per Zilla)
- **Gate Pass Rate**: % of promotions passing each gate
- **Risk Heatmap**: At-risk Zillas (blocked >5 days, low coverage)
- **Dependency Graph**: Zilla → MCP service dependencies
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
  service="archzilla",
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
- [ ] Register all 8 Zillas in pipeline-mcp
- [ ] Configure quality gates per environment
- [ ] Test gate evaluation logic

### Week 2: Integration
- [ ] Connect qa-mcp for qa_tests gate
- [ ] Connect SecZilla for security_scan gate
- [ ] Setup health_check endpoints

### Week 3: Automation
- [ ] Enable auto-merge for dev promotions
- [ ] Setup GitHub Actions for gate triggers
- [ ] Configure Slack notifications

### Week 4: Monitoring
- [ ] Deploy zilla-observatory dashboards
- [ ] Setup alerting rules
- [ ] Create runbooks for common issues

---

## Command Reference

### Register Service
```bash
pipeline-mcp.register_pipeline(
  service="archzilla",
  repo="platform-devs/archzilla-mcp-server"
)
```

### Set Custom Gates
```bash
pipeline-mcp.set_pipeline_config(
  service="archzilla",
  gates_required={
    "hml": ["qa_tests", "pr_approved"],
    "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
  }
)
```

### Record Gate Result
```bash
pipeline-mcp.add_gate_result(
  service="archzilla",
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
  service="archzilla",
  from_env="dev",
  to_env="hml",
  promoted_by="developer@example.com",
  reason="Release v1.3.0 ready for testing"
)
```

### Block Service
```bash
pipeline-mcp.block_service(
  service="archzilla",
  reason="Waiting for security audit completion",
  blocked_by="auditor@example.com"
)
```

---

## Success Criteria

- [x] All 8 Zillas registered in pipeline
- [ ] Quality gates configured and tested
- [ ] Promotion flow working (dev → hml → prod)
- [ ] Gate evaluations reporting correctly
- [ ] Observatory monitoring active
- [ ] Team trained on promotion workflow
- [ ] Runbooks documented

---

## References

- **pipeline-mcp**: `/home/dev/repos/platform-devs/shared/src/mcp-client.ts`
- **zilla-observatory**: `/home/dev/repos/platform-devs/zilla-observatory/`
- **qa-mcp**: Gate evaluation provider
- **SecZilla**: Security gate provider
