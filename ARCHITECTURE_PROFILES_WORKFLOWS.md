# Architecture Analysis: Profiles, Workflows, Tools

**Date**: May 10, 2026  
**Status**: Consolidation Phase  
**MCP Landscape**: 45+ tools across 30 MCPs organized in 4 tiers

---

## Executive Summary

The platform ecosystem consists of **30 interconnected MCPs** serving **5 distinct user profiles**. This document maps how profiles execute 6 critical workflows using specialized and shared tools across Tier 1 (Zilla specialists), Tier 2 (Infrastructure), Tier 3 (Specialized), and Tier 4 (Service MCPs).

**Key Finding**: 3 consolidation opportunities identified to eliminate fragmentation and unify 70+ overlapping tools into 40 canonical tools.

---

## Dimension 1: PROFILES (User Contexts)

### Profile 1: Development (Backend/Frontend Engineer)

**Who**: Backend engineers, Frontend engineers, ArchZilla, BackZilla, FrontZilla  
**Context**: Write code, design APIs, design UIs, test locally, commit changes  
**Primary MCPs**: archzilla, backzilla, frontzilla, qa-mcp, docs-mcp, deploy-mcp  
**Workflow Loop**: Write → Test → Review → Commit → Push → Auto-Deploy to Dev

**Typical Session**:
1. Start: `archzilla.analyze_architecture_requirement()`
2. Code: `backzilla.generate_fastapi_router()` or `frontzilla.generate_react_component()`
3. Test: `qa-mcp.run_unit_tests()` + `qa-mcp.run_type_check()`
4. Review: `qa-mcp.run_linter()` + `docs-mcp.lint_markdown()`
5. Commit: `deploy-mcp.commit_files()`
6. Auto-Deploy: Workflow triggers on develop branch

**Success Metric**: PR merged in <2 hours, all tests passing, zero linter warnings

---

### Profile 2: QA/Release Manager

**Who**: QAZilla, QA engineers, Release managers  
**Context**: Validate quality gates, execute comprehensive testing, promote between environments, sign-off releases  
**Primary MCPs**: qazilla-mcp, test-mcp, quality-gates-system, pipeline-mcp, services-mcp  
**Workflow Loop**: Plan → Execute → Validate → Gate → Promote → Deploy

**Typical Session**:
1. Create Test Plan: `qazilla.create_test_plan(feature, scope)`
2. Generate Scenarios: `qazilla.generate_test_scenarios(category="e2e")`
3. Execute: `qa-mcp.run_e2e_tests(base_url, scenarios)`
4. Record Results: `test-mcp.record_result(scenario_id, status)`
5. Quality Gate: `pipeline-mcp.add_gate_result(service, env, gate_type, passed)`
6. Promote: `pipeline-mcp.promote_service(service, dev→homol, approved_by="qa_manager")`
7. Health Check: `services-mcp.check_health(service_name)`

**Success Metric**: 100% test coverage, all gates passing, production health > 99.9%

---

### Profile 3: Governance/Security/Compliance (Auditor)

**Who**: SecZilla, AI-Governance, Compliance officers, Security engineers  
**Context**: Audit decisions, validate contracts, threat modeling, LGPD/SOC2 compliance  
**Primary MCPs**: seczilla-mcp, ai-governance-mcp, audit-mcp, docs-mcp  
**Workflow Loop**: Threat Model → Risk Assessment → Control Design → Audit → Evidence

**Typical Session**:
1. Analyze: `seczilla.generate_threat_model(application, architecture)`
2. Design Controls: `seczilla.generate_security_controls(threats)`
3. Validate: `ai-governance-mcp.validate_agent_decision(repo, task, proposed_change)`
4. Scan: `qa-mcp.run_security_scan(repo_path, framework="auto")`
5. Document: `docs-mcp.generate_doc(template="ADR", variables={...})`
6. Audit Trail: `audit-mcp` records all decisions with actor + rationale

**Success Metric**: Zero critical vulnerabilities, all contracts validated, 100% audit coverage

---

### Profile 4: Infrastructure/DevOps/SRE (Ops)

**Who**: OpsZilla, SRE engineers, Infrastructure team, Ops managers  
**Context**: IaC design, deployment automation, monitoring, incident response, scaling  
**Primary MCPs**: opszilla-mcp, infra-mcp, pipeline-mcp, services-mcp, zilla-observatory  
**Workflow Loop**: Plan → Provision → Deploy → Monitor → Auto-Remediate

**Typical Session**:
1. Design: `opszilla.generate_terraform_module(cloud_provider, resources)`
2. Validate IaC: `infra-mcp.terraform_validate(path)`
3. Plan: `infra-mcp.terraform_plan(path, out_file)`
4. Cost Check: `infra-mcp.cost_estimate_infracost(plan_path, delta_threshold=100)`
5. Policy Scan: `infra-mcp.policy_scan_checkov(path, framework="terraform")`
6. Deploy: `deploy-mcp.deploy(service, environment="prod")`
7. Monitor: `zilla-observatory.get_service_metrics(service, time_range="1h")`
8. Alert: `zilla-observatory.configure_alert(metric, threshold, action)`

**Success Metric**: Infrastructure as code 100% compliant, zero policy violations, <5min recovery time

---

### Profile 5: Product/Strategy (PM)

**Who**: ProductZilla, POZilla, Product managers, Stakeholders  
**Context**: Define features, roadmap, metrics, success criteria, go-to-market strategy  
**Primary MCPs**: productzilla-mcp, pozilla-mcp, analytics-mcp, scheduler-mcp  
**Workflow Loop**: Discover → Define → Prioritize → Launch → Measure

**Typical Session**:
1. Analyze: `productzilla.analyze_product_problem()`
2. Define Vision: `productzilla.define_product_vision()`
3. Generate Spec: `productzilla.generate_feature_spec()`
4. Handoff: `productzilla.generate_handoff_to_engineering()`
5. Create Epic: `pozilla.generate_epic()`
6. Breakdown: `pozilla.generate_feature_breakdown()`
7. Prioritize: `pozilla.prioritize_backlog_items(framework="RICE")`
8. Measure: `analytics-mcp.get_feature_metrics(feature_id, metrics=[...])`

**Success Metric**: Feature adoption > target KPI, NPS improvement, revenue impact positive

---

## Dimension 2: WORKFLOWS (Critical Execution Paths)

### Workflow A: Feature Development (Parallel Dev + Design + QA)

```
Timeline: 2–4 weeks | Participants: Dev (BackZilla), Design (FrontZilla), 
          Arch (ArchZilla), QA (QAZilla), Ops (OpsZilla), Security (SecZilla)

PHASE 1: DISCOVERY & PLANNING (Week 0)
├─ ProductZilla: analyze_product_problem()
├─ POZilla: generate_feature_breakdown()
└─ ProductZilla: generate_handoff_to_engineering()

PHASE 2: ARCHITECTURE & DESIGN (Week 1, Parallel)
├─ ArchZilla: analyze_architecture_requirement()
│  └─ Call: ai-governance.validate_contract()
├─ FrontZilla: analyze_requirement()
│  └─ FrontZilla: generate_wireframe()
│  └─ FrontZilla: generate_component_spec()
└─ OpsZilla: analyze_infrastructure_requirement()
   └─ OpsZilla: generate_terraform_module()

PHASE 3: IMPLEMENTATION (Week 1-2, Parallel)
├─ BackZilla: generate_fastapi_router()
│  ├─ BackZilla: generate_database_schema()
│  ├─ BackZilla: generate_service_layer()
│  ├─ BackZilla: generate_migration()
│  └─ Call: qa-mcp.run_unit_tests() + qa-mcp.run_security_scan()
│
├─ FrontZilla: generate_react_component()
│  ├─ FrontZilla: generate_custom_hook()
│  ├─ FrontZilla: generate_form_with_validation()
│  └─ Call: qa-mcp.check_accessibility(url, standard="WCAG2AA")
│
└─ OpsZilla: generate_kubernetes_manifest()
   ├─ OpsZilla: generate_docker_compose() [local dev]
   ├─ Call: infra-mcp.terraform_plan()
   └─ Call: infra-mcp.policy_scan_checkov()

PHASE 4: SECURITY REVIEW (Week 2)
├─ SecZilla: generate_threat_model(feature, architecture)
├─ SecZilla: generate_security_controls(threats)
├─ Call: qa-mcp.run_security_scan(repo_path)
├─ Call: docs-mcp.generate_doc(template="ADR")
└─ Call: ai-governance.validate_lib_change() [if applicable]

PHASE 5: COMPREHENSIVE TESTING (Week 2-3)
├─ QAZilla: create_test_plan(feature, scope)
├─ QAZilla: generate_test_scenarios(category="rest_api")
├─ QAZilla: generate_e2e_tests(framework="playwright")
├─ QAZilla: generate_gherkin_scenarios()
└─ Call: qa-mcp.run_e2e_tests(base_url, test_path)

PHASE 6: RELEASE DECISION (Week 3)
├─ POZilla: validate_story_readiness()
├─ QAZilla: generate_quality_gate(criteria=[...])
├─ Call: quality-gates-system.release_gate(service, env="homol")
└─ Call: pipeline.promote_service(service, homol→prod)

PHASE 7: DEPLOYMENT & MONITORING (Week 3-4)
├─ OpsZilla: release via deploy-mcp.deploy(service, env="prod")
├─ Call: services-mcp.check_health(service)
├─ Call: zilla-observatory.configure_alert(metric, threshold)
└─ Call: analytics.track_feature_metrics(feature_id)

SUCCESS CRITERIA:
✅ 100% acceptance criteria passing
✅ >80% code coverage (backend), >70% (frontend)
✅ Zero critical vulnerabilities
✅ All security controls implemented
✅ Performance baseline met (p95 < 200ms)
✅ 99.9% uptime in prod
```

---

### Workflow B: Threat Modeling & Security Review

```
Timeline: 1–2 weeks | Participants: SecZilla, ArchZilla, BackZilla, QA team

PHASE 1: THREAT IDENTIFICATION
├─ SecZilla: generate_threat_model(application, architecture)
│  └─ Store in seczilla.db: threat_models table
├─ SecZilla: map_security_risks()
└─ Call: ai-governance.validate_agent_decision(
      repository="platform-x",
      task="Security Review",
      modifies_security=true
   )

PHASE 2: CONTROL DESIGN
├─ SecZilla: generate_security_controls(threats)
├─ SecZilla: generate_security_architecture(security_requirements)
└─ SecZilla: validate_against_standards(controls, standard="NIST-800-53")

PHASE 3: DEPENDENCY & VULNERABILITY SCANNING
├─ Call: qa-mcp.check_dependencies(repo_path)
├─ Call: qa-mcp.run_security_scan(repo_path, framework="auto")
└─ Result: Report critical vulnerabilities, CVSS scores, fix priorities

PHASE 4: DOCUMENTATION & APPROVAL
├─ Call: docs-mcp.generate_doc(template="ADR", variables={decision: "Security architecture"})
├─ SecZilla: generate_security_handbook()
└─ SecZilla: publish_security_requirements(
      notify=[archzilla, backzilla, opszilla],
      blockers_critical=true
   )

PHASE 5: EVIDENCE & AUDIT
├─ All decisions logged to audit-mcp
├─ Call: audit-mcp.get_audit_log(query="stats")
└─ SecZilla creates ticket for implementation teams

SUCCESS CRITERIA:
✅ All OWASP Top 10 addressed
✅ Zero critical+high vulnerabilities
✅ All dependencies up-to-date
✅ Security controls documented in ADRs
✅ 100% control coverage in implementation
```

---

### Workflow C: Deployment Pipeline (Dev → Homol → Prod)

```
Timeline: Hours to days | Participants: DevOps (OpsZilla), QA (QAZilla), Release Manager

ENTRY: PR created on develop branch → automated flow begins

PHASE 1: AUTOMATED VALIDATION (CI)
├─ deploy-mcp.trigger_workflow(repo, workflow="ci.yml", ref="develop")
├─ GitHub Actions runs:
│  ├─ qa-mcp.run_unit_tests(repo_path, coverage=true)
│  ├─ qa-mcp.run_linter(repo_path)
│  ├─ qa-mcp.run_type_check(repo_path)
│  ├─ qa-mcp.run_security_scan(repo_path)
│  └─ docs-mcp.check_required_docs(repo_path, standard="standard")
├─ pipeline-mcp.add_gate_result(service, "dev", "code_quality", passed=true)
└─ If all pass → PR auto-merged to develop

PHASE 2: PROMOTE TO HOMOL (DEV → HOMOL)
├─ Release Manager: pipeline-mcp.promote_service(
      service="platform-x",
      from_env="dev",
      to_env="homol",
      promoted_by="release_manager"
   )
├─ Creates PR: develop → release/v1.2.3
├─ Status: waiting_approval
├─ QA executes:
│  ├─ qa-mcp.run_e2e_tests(base_url="homol.internal", test_path="./e2e")
│  ├─ qazilla.create_test_plan() + qazilla.generate_test_scenarios()
│  └─ test-mcp.record_result(scenario_id, status="passed")
├─ pipeline-mcp.add_gate_result(service, "homol", "e2e_tests", passed=true)
├─ pipeline-mcp.add_gate_result(service, "homol", "health_check", passed=true)
└─ Release Manager approves: pipeline-mcp.approve_promotion(
      promotion_id=123,
      approved_by="release_manager"
   )

PHASE 3: DEPLOY TO HOMOL
├─ deploy-mcp.deploy(service, environment="homol")
├─ Triggers workflow: .github/workflows/cd-homol.yml
├─ Execution:
│  ├─ docker build + docker push to ACR
│  ├─ kubectl apply manifests
│  └─ Smoke tests run
├─ services-mcp.check_health(service_name)
│  └─ Result: healthy | unhealthy | unknown
└─ If unhealthy → auto-rollback via pipeline-mcp.rollback()

PHASE 4: PROMOTE TO PROD (HOMOL → PROD)
├─ Release Manager: pipeline-mcp.promote_service(
      service="platform-x",
      from_env="homol",
      to_env="prod",
      promoted_by="release_manager"
   )
├─ Creates PR: release/v1.2.3 → main (production)
├─ Status: waiting_approval
├─ Additional gates in PROD:
│  ├─ pipeline-mcp.add_gate_result(..., "manual_approval", passed=true)
│  └─ Requires approval from ops-manager (GitHub environment protection)
└─ Release Manager approves: pipeline-mcp.approve_promotion(...)

PHASE 5: DEPLOY TO PROD
├─ deploy-mcp.deploy(service, environment="prod")
├─ Triggers workflow: .github/workflows/cd-prod.yml
├─ Blue-green deployment:
│  ├─ Deploy to new nodes
│  ├─ Health checks pass
│  ├─ Traffic migration (10% → 50% → 100%)
│  └─ Keep old version ready for rollback (5 minutes window)
├─ services-mcp.check_health(service_name, timeout=10)
└─ zilla-observatory.configure_alert(
      metric="error_rate",
      threshold=0.01,
      action="page_on_call"
   )

PHASE 6: MONITORING & ROLLBACK (ON-CALL)
├─ Real-time monitoring via zilla-observatory
├─ If issues detected:
│  ├─ SRE: pipeline-mcp.rollback(
│       service="platform-x",
│       env="prod",
│       to_version="v1.2.2",
│       rolled_back_by="on_call_engineer"
│     )
│  └─ Automatic re-deployment of previous version
└─ Post-incident: Incident review + learning doc

SUCCESS CRITERIA:
✅ All PRs auto-merged to develop within 2 hours
✅ Homol deployment <30 minutes
✅ Prod deployment <5 minutes
✅ Blue-green strategy working (0 downtime)
✅ 100% gate passage rate
✅ Zero production incidents related to this feature
```

---

### Workflow D: Cross-Zilla Validation (Ecosystem Health Check)

```
Timeline: Daily, automated | Participants: ai-governance-mcp, cross-zilla-validators

PHASE 1: ECOSYSTEM GRAPH ANALYSIS
├─ ai-governance.query_ecosystem_graph(node_id=None, query="stats")
└─ Returns: 
    {total_nodes: 204, total_edges: 97, orphaned_services: 0, breaking_changes: []}

PHASE 2: CONTRACT VALIDATION
├─ For each service:
│  ├─ ai-governance.find_consumers_of(service_id)
│  ├─ ai-governance.find_dependencies_of(service_id, include_transitive=true)
│  └─ cross-zilla-validators.validate_contract_compatibility(
│       provider=service_id,
│       consumers=[...],
│       contract_type="api"
│     )
└─ Report: Breaking changes, missing consumers, orphaned edges

PHASE 3: SUGGESTION VALIDATION
├─ cross-zilla-validators.validate_suggestion_cross_repo(
      source_repo="platform-auth",
      target_repo="platform-gateway",
      suggestion_type="improvement"
   )
├─ ai-governance.list_suggestions(status="pending")
└─ Route to appropriate team via session-mcp.submit_suggestion()

PHASE 4: GOVERNANCE CHECK
├─ ai-governance.validate_lib_change(lib_name="platform-db-vector", proposed_change="...")
│  └─ HARD STOP if lib is platform-*-lib (requires approval)
├─ ai-governance.validate_migration(content=migration_sql)
│  └─ HARD STOP if missing idempotence or no downgrade
└─ ai-governance.validate_agent_decision(
      repository="any",
      proposed_change="...",
      adds_dependency=true,
      modifies_security=false
   )

SUCCESS CRITERIA:
✅ Zero broken contracts
✅ Zero orphaned services
✅ <5% suggestion deferral rate
✅ 100% governance compliance
```

---

### Workflow E: Release Management (Version Bump & Go-Live)

```
Timeline: 1 week per release cycle | Participants: POZilla, Release Manager, All MCPs

PHASE 1: DEFINE RELEASE
├─ POZilla: generate_release_notes(version, features, fixes)
├─ POZilla: generate_release_plan(version, phases, timeline)
└─ Notify: All teams via ai-governance.broadcast()

PHASE 2: PREPARE DEPLOYMENT
├─ For each service in release:
│  ├─ Create release branch: git tag v1.2.3
│  ├─ Update CHANGELOG.md via docs-mcp.generate_doc(template="CHANGELOG")
│  └─ Trigger release workflow
└─ Staging deployment (homol) for final validation

PHASE 3: EXECUTION
├─ Day 1: Deploy to homol, run full E2E + smoke tests
├─ Day 2-3: QA signs off, security review closes
├─ Day 4: Release window opens
├─ Day 4 (T-0): Blue-green deployment to prod
├─ Day 4 (T+10m): Verify metrics, check zero-error window
└─ Day 4 (T+30m): Keep old version on standby

PHASE 4: ROLLBACK READINESS
├─ pipeline-mcp maintains previous version ready for <5min rollback
├─ If rollback triggered: all traffic shifted back
└─ Post-rollback: incident review + root cause analysis

SUCCESS CRITERIA:
✅ 100% feature adoption by target date
✅ Zero incidents in 24h post-deployment
✅ Rollback time <5 minutes if needed
✅ 99.95% SLA maintained
```

---

### Workflow F: Governance & Audit Trail

```
Timeline: Continuous | Participants: audit-mcp, ai-governance-mcp, session-mcp

PHASE 1: DECISION LOGGING
├─ Every significant action recorded:
│  ├─ session-mcp.add_artifact(session_id, "decision", description)
│  ├─ session-mcp.approve_task(task_id, decision="go", actor=...)
│  └─ session-mcp.complete_task(task_id, commit_sha, commit_message)
├─ Auto-recorded: Who, What, When, Why, Outcome
└─ Stored in session-mcp + audit-mcp (immutable logs)

PHASE 2: AUDIT TRAIL ACCESS
├─ audit-mcp.get_audit_log(query="stats")
│  └─ Returns: {total_decisions: N, by_risk_level: {...}, by_repo: {...}}
├─ audit-mcp.get_audit_log(filter_repo="platform-x", limit=50)
│  └─ Returns: Timestamped list of all decisions for repo
└─ Retention: 7 years (compliance requirement)

PHASE 3: COMPLIANCE REPORTING
├─ Generate audit reports for:
│  ├─ SOC 2: All access decisions + authentication events
│  ├─ GDPR: Data processing decisions + deletions
│  └─ NIST: Security posture + control effectiveness
└─ Exported to docs-mcp for storage + archival

SUCCESS CRITERIA:
✅ 100% decision coverage in audit trail
✅ Zero gaps in decision chain
✅ <1s latency for audit queries
✅ 7-year data retention compliance
```

---

## Dimension 3: TOOLS (Consolidation Opportunities)

### Current Distribution (45+ MCPs, 350+ tools)

```
TIER 1: ZILLA SPECIALISTS (8 MCPs, 134 tools)
├─ FrontZilla: 30 tools (25.9%)
├─ OpsZilla: 19 tools (16.4%)
├─ ArchZilla: 18 tools (15.5%)
├─ ProductZilla: 18 tools (15.5%)
├─ POZilla: 17 tools (14.7%)
├─ BackZilla: 14 tools (12.1%)
├─ QAZilla: 20 tools (17.2%)
└─ SecZilla: 20 tools (17.2%)

TIER 2: INFRASTRUCTURE (12 MCPs, 130+ tools)
├─ deploy-mcp: 15 tools
├─ qa-mcp: 15 tools
├─ ai-governance-mcp: 14 tools
├─ session-mcp: 12 tools
├─ docs-mcp: 12 tools
├─ pipeline-mcp: 10 tools
├─ test-mcp: 10 tools
├─ infra-mcp: 9 tools
├─ services-mcp: 8 tools
├─ config-mcp: 8 tools
├─ audit-mcp: 5 tools
└─ agent-twin-mcp: 4 tools

TIER 3: SPECIALIZED (3 MCPs, 36 tools)
├─ zilla-observatory: 20 tools
├─ knowledge-base-mcp: 6 tools
└─ cross-zilla-validators: 10 tools

TIER 4: SERVICES (10 MCPs, 75+ tools)
├─ monitor-mcp: 10 tools
├─ ml-mcp: 9 tools
├─ datalake-mcp: 8 tools
├─ admin-mcp: 8 tools
├─ connectors-mcp: 8 tools
├─ analytics-mcp: 7 tools
├─ governance-mcp: 7 tools
├─ cache-mcp: 6 tools
├─ scheduler-mcp: 6 tools
└─ auth-mcp: 8 tools

TOTAL: ~375 tools across 45 MCPs
```

### Problem 1: Testing Fragmentation (70+ Overlapping Tools)

**Current State**:
- **qazilla-mcp**: 20 tools (test planning, generation, automation, bug management, quality gates)
- **qa-mcp**: 15 tools (run_unit_tests, run_linter, run_security_scan, check_coverage, etc.)
- **test-mcp**: 10 tools (create_test_plan, generate_scenarios, record_result, run_checklist, etc.)

**Overlaps**:
- `qazilla.generate_unit_tests` + `qa-mcp.run_unit_tests` + `test-mcp` setup
- `qazilla.generate_e2e_tests` + `qa-mcp.run_e2e_tests`
- `qazilla.generate_gherkin_scenarios` + `test-mcp.generate_scenarios`
- `qazilla.create_test_plan` + `test-mcp.create_test_plan`

**Recommendation: Consolidate into QAZilla**
```
BEFORE:
  qazilla-mcp (20) → design test strategy
  qa-mcp (15) → execute tests
  test-mcp (10) → manage test plans
  Total: 45 tools, 3 MCPs

AFTER:
  qazilla-mcp (45) → unified QA + testing dominio
    ├─ 20 original tools
    ├─ 15 qa-mcp tools wrapped: run_unit_tests → qazilla.run_unit_tests()
    ├─ 10 test-mcp tools wrapped: create_test_plan → qazilla.create_test_plan()
  Result: -2 MCPs, 1 unified context for QA teams
```

**Migration Path**:
1. Move qa-mcp.run_unit_tests → qazilla.run_unit_tests (wrapper calling qa-mcp internally)
2. Move test-mcp.create_test_plan → qazilla.create_test_plan (wrapper)
3. Deprecate test-mcp (no breaking changes)
4. Deprecate qa-mcp.run_* public APIs (keep internal for other MCPs)
5. Update all references in workflows to use qazilla directly

---

### Problem 2: Security Tool Fragmentation (40+ Overlapping Tools)

**Current State**:
- **seczilla-mcp**: 20 tools (threat modeling, control design, review)
- **qa-mcp**: 3 tools (run_security_scan, check_dependencies, analyze_complexity)
- **ai-governance-mcp**: 14 tools (validation, contract checking)

**Overlaps**:
- `seczilla.review_secure_code` + `qa-mcp.run_security_scan`
- `seczilla.validate_against_standards` + `ai-governance.validate_contract`

**Recommendation: Integrate SecZilla with QA, Keep ai-governance Separate**
```
BEFORE:
  seczilla-mcp (20) → threat & control design
  qa-mcp (3) → security scanning/audit
  ai-governance-mcp (14) → governance + contracts
  Total: 37 tools dedicated to security

AFTER:
  seczilla-mcp (25) → unified security
    ├─ 20 original tools
    ├─ 5 new tools: run_security_scan(), check_dependencies(), validate_threat_model()
    └─ These call qa-mcp internally (hidden)
  
  qa-mcp (3 deprecated) → tools move to seczilla, qa-mcp becomes internal-only
  
  ai-governance-mcp (14) → KEEP SEPARATE (ecosystem contracts, not security)

Result: Security domain unified in seczilla, ai-governance keeps ecosystem role
```

**Migration Path**:
1. Add wrapper tools to seczilla: `run_security_scan()`, `check_dependencies()`
2. These wrappers call qa-mcp.run_security_scan internally
3. Update seczilla workflows to call `seczilla.run_security_scan()` instead of `qa-mcp`
4. Mark qa-mcp security tools as deprecated (redirect to seczilla)
5. Keep ai-governance separate (different domain: contracts, not security threats)

---

### Problem 3: Observability Fragmentation (30+ Overlapping Tools)

**Current State**:
- **zilla-observatory**: 20 tools (metrics, dashboards, alerts, ecosystem monitoring)
- **monitor-mcp**: 10 tools (logs, metrics, traces, alerts) — Service MCP

**Overlaps**:
- `zilla-observatory.get_service_metrics` + `monitor-mcp.get_metrics`
- `zilla-observatory.configure_alert` + `monitor-mcp.configure_alert`
- `zilla-observatory.get_ecosystem_health` + `monitor-mcp.get_health_check`

**Recommendation: Keep Separate (Different Domains)**
```
KEEP AS IS:
  zilla-observatory (20) → Zilla ecosystem + dashboards (MCP specialist)
  monitor-mcp (10) → General platform monitoring (Service MCP)

REASONING:
  - zilla-observatory = DOMAIN: Zilla team's tools + ecosystem dashboards
  - monitor-mcp = DOMAIN: General services + applications
  - No need to merge (clear separation of concerns)
  - Integration: zilla-observatory.configure_alert() calls monitor-mcp internally
```

**Integration Strategy** (no consolidation needed):
1. zilla-observatory stays as primary interface for Zilla teams
2. monitor-mcp stays as service for apps/services to call
3. When zilla-observatory needs metrics → calls monitor-mcp internally
4. Clear domain boundary: Zilla-specific vs. Generic

---

### Problem 4: Ops & Infrastructure (Separate, No Overlap)

**Current State**:
- **opszilla-mcp**: 19 tools (design, docker, k8s, terraform design)
- **infra-mcp**: 9 tools (execution: terraform plan/apply, checkov, cost estimation)

**Status**: GOOD SEPARATION
```
opszilla (19) → DESIGN PHASE
├─ generate_terraform_module()
├─ generate_kubernetes_manifest()
├─ generate_dockerfile()
├─ generate_docker_compose()
└─ Calls infra-mcp for validation

infra-mcp (9) → EXECUTION PHASE
├─ terraform_plan()
├─ terraform_validate()
├─ policy_scan_checkov()
├─ cost_estimate_infracost()
└─ terraform_apply() [if approved]

Clear flow: opszilla designs → infra-mcp executes + validates
```

**Recommendation**: KEEP AS IS (Perfect separation)

---

### Problem 5: Documentation (Good, Just Ensure Reuse)

**Current State**:
- **docs-mcp**: 12 tools (templates, linting, audit, search)
- Each Zilla generates own docs via `generate_doc()` calls

**Status**: GOOD (Cross-MCP pattern)
```
docs-mcp (12) → Shared utilities
├─ generate_doc(template, variables)
├─ check_required_docs()
├─ lint_markdown()
├─ validate_doc()
├─ search_docs()

Usage: Every Zilla calls docs-mcp.generate_doc() to create ADRs, docs
No consolidation needed. Already following best practice.
```

**Recommendation**: KEEP AS IS (Exemplary cross-MCP pattern)

---

## Consolidation Summary Table

| Action | MCPs Affected | Tools Before | Tools After | Benefit | Priority |
|--------|---------------|--------------|-------------|---------|----------|
| **Consolidate Testing** | qazilla ← qa-mcp + test-mcp | 45 tools / 3 MCPs | 45 tools / 1 MCP | -2 MCPs, unified QA context | **P1** |
| **Integrate Security** | seczilla ← qa-mcp (security) | 37 tools / 2 MCPs | 25 tools + 14 in ai-gov / 2 MCPs | Unified threat→control flow | **P1** |
| **Keep Ops Separate** | opszilla + infra-mcp | 28 tools / 2 MCPs | 28 tools / 2 MCPs | Design-execute separation works | ✓ |
| **Keep Observability Integrated** | zilla-observatory + monitor-mcp | 30 tools / 2 MCPs | 30 tools / 2 MCPs | Domain separation clear | ✓ |
| **Docs as Utilities** | docs-mcp (shared) | 12 tools / 1 MCP | 12 tools / 1 MCP | Already exemplary | ✓ |

---

## Implementation Roadmap

### Phase 1: Testing Consolidation (Week 1-2)
1. Add wrapper tools to QAZilla for qa-mcp functions
2. Update QAZilla to call qa-mcp internally
3. Deprecate test-mcp public API
4. Update all workflow documentation

### Phase 2: Security Integration (Week 2-3)
1. Add wrapper tools to SecZilla for qa-mcp security functions
2. Update SecZilla workflows to use `seczilla.run_security_scan()`
3. Deprecate qa-mcp security tools public API
4. Update security workflows

### Phase 3: Cross-MCP Testing (Week 3)
1. End-to-end feature workflow using consolidated MCPs
2. Validate all profiles execute workflows without issues
3. Performance benchmarking

### Phase 4: Documentation & Training (Week 4)
1. Update MCP documentation
2. Training videos for each profile
3. Migration guide for teams

---

## Success Metrics

After consolidation, measure:
- **Tool Reuse**: >85% of tools called by >2 MCPs
- **API Clarity**: <3 similar tools per domain
- **Context Switching**: Dev profile averages <5 MCP hops per session
- **Training Time**: New engineer onboarding <4 hours
- **Workflow Efficiency**: Feature delivery time -20% (from consolidation benefits)

---

## Next Steps

1. **Validate** this analysis with team leads from each profile
2. **Prioritize** consolidations (P1 vs. P2)
3. **Create** detailed migration playbooks for each consolidation
4. **Execute** Phase 1 (Testing)
5. **Measure** impact and iterate

