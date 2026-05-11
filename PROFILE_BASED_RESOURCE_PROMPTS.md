# Profile-Based Resource Prompts: Context-Aware MCP Behavior

**Date**: May 10, 2026  
**Concept**: Each MCP returns context-specific resource prompts based on the calling agent's profile  
**Benefit**: Reduces context switching, speeds up workflows, personalizes experience

---

## Overview

When an MCP is invoked, it should detect the **caller's profile** and return **custom prompts** optimizing for that profile's workflow.

### Example: QAZilla's Context-Aware Behavior

```typescript
// When qazilla.get_resource_prompt() is called:

IF caller_profile == "Development Engineer":
  RETURN: "Quick unit test generation tool. Use: generate_unit_tests(component). Add to CI."
  
IF caller_profile == "QA/Release Manager":
  RETURN: "Complete QA toolkit. Workflow: create_test_plan() → generate_scenarios() → run_e2e_tests() → record_results() → quality_gate(). See QUALITY_GATES_SLA.md"
  
IF caller_profile == "DevOps/SRE":
  RETURN: "Performance + load testing tools. run_k6_performance_test(api_url, concurrent_users). Monitor p95 latency."

IF caller_profile == "Product Manager":
  RETURN: "Not applicable. QA is handled by QA/Release Manager."
```

---

## Profile Detection Mechanism

### Input Variables (from session context)

```typescript
interface ProfileContext {
  user_email: string;           // caio@dataforall.tech
  user_role: string;             // "developer" | "qa_manager" | "security_officer" | "devops_engineer" | "product_manager"
  session_repo: string;          // platform-service-template
  session_branch: string;        // session/legendary-vishnu
  session_objective: string;     // "Feature development"
  recent_tools_called: Tool[];  // Last 5 tools called in this session
  session_duration_minutes: number; // How long has this session been active?
}

// Derive profile:
function detectProfile(context: ProfileContext): Profile {
  if (context.user_role.includes("qa") || context.recent_tools_called.includes("create_test_plan")) {
    return "QA/Release Manager";
  } else if (context.user_role.includes("dev") || context.session_objective.includes("write")) {
    return "Development Engineer";
  } else if (context.user_role.includes("devops")) {
    return "DevOps/SRE";
  } else if (context.user_role.includes("security")) {
    return "Security/Compliance";
  } else if (context.user_role.includes("product")) {
    return "Product Manager";
  }
}
```

### Resource Prompt Format

Each MCP returns:
```json
{
  "mcp_name": "qazilla-mcp",
  "calling_profile": "QA/Release Manager",
  "resource_prompt": "...",
  "quick_start": ["create_test_plan(feature)", "generate_scenarios()"],
  "common_workflows": ["Full QA → Prod Release", "Smoke Test Suite"],
  "learning_resources": ["QA_WORKFLOWS.md", "QUALITY_GATES.md"],
  "related_tools": ["SecZilla (security tests)", "OpsZilla (performance tests)"]
}
```

---

## Profile-Specific Resource Prompts

### Profile 1: Development Engineer (Backend/Frontend)

**Typical Tools Used**: ArchZilla, BackZilla, FrontZilla, qa-mcp, deploy-mcp

#### When calling QAZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ QAZilla: Quick Test Generation Tool                           ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Generate tests for your code as you write               ║
║                                                                 ║
║ QUICK START:                                                   ║
║   1. Write code in BackZilla or FrontZilla                    ║
║   2. qazilla.generate_unit_tests(component="UserService")     ║
║   3. Copy tests to your test file                             ║
║   4. qa-mcp.run_unit_tests(repo_path) to verify             ║
║                                                                 ║
║ MOST COMMON:                                                   ║
║   • generate_unit_tests() — Unit tests for your component    ║
║   • generate_api_tests() — REST API tests                    ║
║   • generate_gherkin_scenarios() — BDD scenarios             ║
║                                                                 ║
║ TIP: Generate tests BEFORE implementing. TDD pattern works!    ║
║                                                                 ║
║ ALSO USEFUL:                                                   ║
║   • SecZilla for security testing                            ║
║   • deploy-mcp for CI/CD integration                         ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling SecZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ SecZilla: Add Security to Your Code                           ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Security best practices BEFORE code review              ║
║                                                                 ║
║ DO THIS:                                                       ║
║   1. Before pushing to develop:                               ║
║   2. seczilla.scan_dependency_risks(repo_path)               ║
║   3. Fix any HIGH/CRITICAL issues                             ║
║   4. Commit + push                                            ║
║                                                                 ║
║ REVIEW AFTER PR:                                              ║
║   • SecZilla reviews OWASP Top 10                             ║
║   • Feedback integrated into your next commit                 ║
║                                                                 ║
║ COMMON ISSUES:                                                 ║
║   • Hardcoded credentials → Use config-mcp                   ║
║   • SQL injection risk → Use ORMs (BackZilla pattern)        ║
║   • Unvalidated input → Add Zod validation                   ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling OpsZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ OpsZilla: Local Dev Environment Setup                         ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Docker + local infrastructure for development           ║
║                                                                 ║
║ START HERE:                                                    ║
║   opszilla.generate_docker_compose(services=["postgres", "redis"])
║   docker-compose up                                            ║
║                                                                 ║
║ ADD TO YOUR SETUP:                                             ║
║   • postgres for data storage                                 ║
║   • redis for caching                                         ║
║   • kafka for events (if needed)                             ║
║                                                                 ║
║ FOR DEPLOYMENT (later):                                       ║
║   • Talk to DevOps team (OpsZilla + infra-mcp)             ║
║   • You provide: Dockerfile, health checks                    ║
║   • They handle: K8s, terraform, scaling                     ║
╚════════════════════════════════════════════════════════════════╝
```

---

### Profile 2: QA/Release Manager

**Typical Tools Used**: QAZilla, test-mcp, pipeline-mcp, quality-gates-system

#### When calling QAZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ QAZilla: Complete QA Workflow                                 ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Orchestrate full testing + release quality gates        ║
║                                                                 ║
║ FULL WORKFLOW (2-3 weeks):                                    ║
║   WEEK 1: Planning                                            ║
║     • qazilla.create_test_plan(feature="User Auth", ...)    ║
║     • qazilla.generate_test_scenarios(category="auth_flow")  ║
║                                                                 ║
║   WEEK 2: Execution                                           ║
║     • qazilla.run_e2e_tests(base_url="dev.internal")        ║
║     • qazilla.generate_uat_checklist(feature="User Auth")    ║
║     • qazilla.run_checklist() to validate                    ║
║                                                                 ║
║   WEEK 3: Release                                             ║
║     • qazilla.generate_quality_gate(gate_name="UAT Pass")    ║
║     • pipeline.promote_service() when all gates pass         ║
║     • qazilla.generate_regression_suite() for next release   ║
║                                                                 ║
║ KEY METRICS:                                                   ║
║   • Test Coverage: Target >85% (backend), >70% (frontend)    ║
║   • Pass Rate: 100% before promotion                          ║
║   • Test Execution Time: <30 min for full suite              ║
║                                                                 ║
║ SHORTCUT: qazilla.generate_k6_performance_test() for load    ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling Pipeline MCP:
```
╔════════════════════════════════════════════════════════════════╗
║ Pipeline: Environment Promotion & Release Gates               ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Manage flow dev → homol → prod                         ║
║                                                                 ║
║ GATE STATUS CHECK:                                            ║
║   pipeline.get_gate_status(service="platform-x", env="homol")║
║   Returns: {qa_tests: PASSED, security: PASSED, health: ...} ║
║                                                                 ║
║ PROMOTE SERVICE:                                              ║
║   pipeline.promote_service(                                   ║
║     service="platform-x",                                     ║
║     from_env="dev",                                           ║
║     to_env="homol",                                           ║
║     promoted_by="qa_manager"                                  ║
║   )                                                             ║
║   → Creates PR: develop → release/v1.2.3                     ║
║   → Status: waiting_approval                                   ║
║                                                                 ║
║ AFTER HOMOL VALIDATION:                                       ║
║   pipeline.approve_promotion(promotion_id=123,...)           ║
║   → Merges PR + deploys to homol                             ║
║                                                                 ║
║ DEPLOY TO PROD:                                               ║
║   Same process: homol → prod (requires manual approval)      ║
║                                                                 ║
║ IF ISSUES:                                                     ║
║   pipeline.rollback(service="platform-x", to_version="v1.2.2")
║   → Reverts to previous version (< 5 min)                     ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling SecZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ SecZilla: Security Testing Before Release                     ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Validate security controls before production            ║
║                                                                 ║
║ BEFORE HOMOL PROMOTION:                                       ║
║   seczilla.run_security_scan(repo_path="./platform-x")      ║
║   → Detects: SQL injection, hardcoded secrets, vulns         ║
║                                                                 ║
║ REQUIRED GATE:                                                ║
║   BEFORE homol: seczilla results must be CLEARED             ║
║   → pipeline won't promote until security OK                  ║
║                                                                 ║
║ DEPENDENCY RISKS:                                             ║
║   seczilla.check_dependencies() before production             ║
║   → Blocks if CRITICAL vulnerabilities found                 ║
║                                                                 ║
║ SLA: Security gate must pass before Prod                      ║
╚════════════════════════════════════════════════════════════════╝
```

---

### Profile 3: Security/Compliance Officer

**Typical Tools Used**: SecZilla, ai-governance-mcp, audit-mcp, docs-mcp

#### When calling SecZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ SecZilla: Complete Threat & Control Management               ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Architecture + threat modeling + evidence collection    ║
║                                                                 ║
║ THREAT MODELING WORKFLOW:                                     ║
║   1. New feature → seczilla.generate_threat_model(app, arch) ║
║   2. Review threats + map to OWASP Top 10                    ║
║   3. seczilla.generate_security_controls(threats)            ║
║   4. Document in ADR: seczilla.generate_security_architecture║
║   5. Notify teams: Controls required for implementation      ║
║                                                                 ║
║ DURING DEVELOPMENT:                                           ║
║   Teams implement controls →                                  ║
║   seczilla.validate_security_controls(threats, evidence)     ║
║   → Confirm all threats mitigated                             ║
║                                                                 ║
║ BEFORE RELEASE:                                               ║
║   seczilla.run_security_scan(repo_path)                      ║
║   seczilla.validate_threat_model(threats, scan_evidence)     ║
║   → All threats verified by evidence                          ║
║                                                                 ║
║ COMPLIANCE REPORTING:                                         ║
║   Audit trail maintained in audit-mcp                         ║
║   Evidence stored in seczilla.db                              ║
║   Ready for: SOC 2, GDPR, NIST audits                        ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling ai-governance-mcp:
```
╔════════════════════════════════════════════════════════════════╗
║ AI-Governance: Ecosystem Validation & Contract Review         ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Cross-repo compliance + breaking change detection       ║
║                                                                 ║
║ VALIDATE BREAKING CHANGES:                                    ║
║   ai-governance.validate_lib_change(                          ║
║     lib_name="platform-db-vector",                            ║
║     proposed_change="Remove cache() function"                 ║
║   )                                                             ║
║   → HARD STOP if lib is platform-*-lib                        ║
║   → Identify all consumers auto (ecosystem graph)             ║
║   → Mark as "LIB CHANGE REQUEST" → needs approval            ║
║                                                                 ║
║ VALIDATE CONTRACT CHANGES:                                    ║
║   ai-governance.get_contract_change_policy(                  ║
║     provider_service="platform-auth",                         ║
║     contract_type="api",                                      ║
║     proposed_change="Remove /auth/refresh endpoint"          ║
║   )                                                             ║
║   → Returns required tests + approval process                 ║
║                                                                 ║
║ VALIDATE DECISIONS:                                           ║
║   ai-governance.validate_agent_decision(                      ║
║     repository="platform-gateway",                            ║
║     proposed_change="Add new dependency",                     ║
║     adds_dependency=true,                                     ║
║     modifies_security=true                                    ║
║   )                                                             ║
║   → Blocks if risks detected                                  ║
║   → Requires human approval                                   ║
║                                                                 ║
║ AUDIT TRAIL:                                                  ║
║   All decisions logged + decision metadata stored             ║
║   Ready for compliance audits                                 ║
╚════════════════════════════════════════════════════════════════╝
```

---

### Profile 4: DevOps/SRE Engineer

**Typical Tools Used**: OpsZilla, infra-mcp, pipeline-mcp, services-mcp, zilla-observatory

#### When calling OpsZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ OpsZilla: Infrastructure Design & Deployment                  ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Design deployment architecture, templates, K8s manifests║
║                                                                 ║
║ DESIGN PHASE:                                                  ║
║   opszilla.generate_terraform_module(                         ║
║     cloud_provider="gcp",                                     ║
║     resources=["compute", "database", "networking"]           ║
║   )                                                             ║
║                                                                 ║
║   opszilla.generate_kubernetes_manifest(                      ║
║     application="platform-gateway",                           ║
║     replicas=3,                                               ║
║     resources={cpu: "500m", memory: "512Mi"}                 ║
║   )                                                             ║
║                                                                 ║
║ VALIDATION PHASE (→ infra-mcp):                              ║
║   infra-mcp.terraform_validate(path)                          ║
║   infra-mcp.policy_scan_checkov(path)                         ║
║   infra-mcp.terraform_plan(path)                              ║
║   infra-mcp.cost_estimate_infracost(plan_path)               ║
║                                                                 ║
║ DEPLOYMENT PHASE (→ deploy-mcp):                             ║
║   deploy-mcp.deploy(service="platform-gateway", env="prod")  ║
║   services-mcp.check_health(service)                          ║
║   zilla-observatory.get_service_metrics(service)             ║
║                                                                 ║
║ MONITORING & AUTO-REMEDIATION:                                ║
║   zilla-observatory.configure_alert(metric, threshold)       ║
║   If metric breaches → auto-scaling or paging                ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling infra-mcp:
```
╔════════════════════════════════════════════════════════════════╗
║ Infra MCP: Terraform Execution & Policy Validation            ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Validate, plan, cost-estimate, scan policies, apply     ║
║                                                                 ║
║ CHECKLIST (before deployment):                                ║
║   1. infra-mcp.terraform_validate(path)                       ║
║      → Syntax check                                            ║
║   2. infra-mcp.terraform_plan(path, out_file)                 ║
║      → Shows what will change (review with team)              ║
║   3. infra-mcp.policy_scan_checkov(path)                      ║
║      → BLOCKS on HIGH/CRITICAL policy violations              ║
║   4. infra-mcp.cost_estimate_infracost(plan_path)            ║
║      → Alert if delta > +$100/month or +20%                  ║
║                                                                 ║
║ DEPLOYMENT:                                                    ║
║   → Review plan output with stakeholders                       ║
║   → Get approval (if cost delta significant)                   ║
║   → deploy-mcp.deploy() to apply                             ║
║                                                                 ║
║ ROLLBACK:                                                      ║
║   If issues: terraform destroy (or previous plan)            ║
║             pipeline-mcp.rollback() for services             ║
║                                                                 ║
║ SLA: All checks must pass before production changes          ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling zilla-observatory:
```
╔════════════════════════════════════════════════════════════════╗
║ Zilla-Observatory: Real-Time Monitoring & Dashboards          ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Monitor ecosystem health, dashboards, alerts, SLA       ║
║                                                                 ║
║ QUICK HEALTH CHECK:                                           ║
║   zilla-observatory.get_ecosystem_health()                    ║
║   → Returns: {services: 40, healthy: 38, unhealthy: 2}       ║
║                                                                 ║
║ SERVICE METRICS:                                              ║
║   zilla-observatory.get_service_metrics(                      ║
║     service="platform-gateway",                               ║
║     metrics=["error_rate", "p95_latency", "throughput"]      ║
║   )                                                             ║
║   → Last 1h, 24h, 7d, 30d windows                             ║
║                                                                 ║
║ ALERTS:                                                        ║
║   zilla-observatory.configure_alert(                          ║
║     metric="error_rate",                                      ║
║     threshold=0.01,  // 1%                                    ║
║     action="page_on_call"                                     ║
║   )                                                             ║
║                                                                 ║
║ DASHBOARDS:                                                    ║
║   zilla-observatory.generate_grafana_dashboard(...)           ║
║   → Real-time view of ecosystem + services                    ║
║                                                                 ║
║ ON-CALL INCIDENT:                                             ║
║   1. Alert fires → Page on-call                               ║
║   2. Review dashboard + service metrics                        ║
║   3. If needed: pipeline-mcp.rollback()                      ║
║   4. Post-incident: Generate learning doc                    ║
╚════════════════════════════════════════════════════════════════╝
```

---

### Profile 5: Product Manager

**Typical Tools Used**: ProductZilla, POZilla, analytics-mcp, scheduler-mcp

#### When calling ProductZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ ProductZilla: Product Strategy & Roadmap                      ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Define product direction, features, success metrics     ║
║                                                                 ║
║ QUARTERLY PLANNING:                                           ║
║   1. productzilla.analyze_product_problem(problem_statement) ║
║   2. productzilla.define_product_vision()                    ║
║      → Target users, market, 5-year vision                   ║
║   3. productzilla.define_product_metrics()                   ║
║      → KPIs: user adoption, NPS, revenue impact             ║
║   4. productzilla.map_user_journey()                         ║
║      → Understanding user touchpoints                         ║
║   5. productzilla.map_user_personas()                        ║
║      → Market segments + personas                             ║
║                                                                 ║
║ FEATURE DEFINITION:                                           ║
║   productzilla.generate_feature_spec(                        ║
║     feature="User Onboarding",                               ║
║     target_user="New users < 1 week"                         ║
║   )                                                             ║
║   → Acceptance criteria, user value, scope                    ║
║                                                                 ║
║ HANDOFF TO ENGINEERING:                                       ║
║   productzilla.generate_handoff_to_engineering()             ║
║   → Requirements for dev + ops + QA                          ║
║                                                                 ║
║ LAUNCH PLANNING:                                              ║
║   productzilla.generate_go_to_market_brief()                 ║
║   → Target segment, messaging, channels, timing              ║
║                                                                 ║
║ MEASUREMENT:                                                   ║
║   analytics-mcp.get_feature_metrics(                          ║
║     feature_id="user_onboarding",                            ║
║     date_range="last_30_days"                                ║
║   )                                                             ║
║   → Adoption rate, NPS lift, retention impact                ║
╚════════════════════════════════════════════════════════════════╝
```

#### When calling POZilla:
```
╔════════════════════════════════════════════════════════════════╗
║ POZilla: Sprint Planning & Backlog Management                 ║
╠════════════════════════════════════════════════════════════════╣
║ Role: Translate features into prioritized user stories        ║
║                                                                 ║
║ FEATURE BREAKDOWN:                                            ║
║   pozilla.generate_feature_breakdown(                        ║
║     feature="User Onboarding"                                 ║
║   )                                                             ║
║   → Breaks into 8-12 stories                                  ║
║                                                                 ║
║ BACKLOG PRIORITIZATION:                                       ║
║   pozilla.prioritize_backlog_items(                          ║
║     framework="RICE",  // Reach × Impact × Confidence / Effort║
║     items=[story1, story2, ...]                              ║
║   )                                                             ║
║   → Ordered by value                                          ║
║                                                                 ║
║ SPRINT PREPARATION:                                           ║
║   pozilla.prepare_sprint_backlog(                            ║
║     stories=[...],                                            ║
║     sprint_days=10,                                           ║
║     team_velocity=40  // story points per sprint              ║
║   )                                                             ║
║   → Stories fit in sprint, ordered                             ║
║                                                                 ║
║ ACCEPTANCE CRITERIA:                                          ║
║   pozilla.generate_acceptance_criteria(                      ║
║     story="As a user, I want to reset password"             ║
║   )                                                             ║
║   → GIVEN/WHEN/THEN format (testable)                       ║
║                                                                 ║
║ RELEASE NOTES:                                                 ║
║   pozilla.generate_release_notes(                            ║
║     version="v2.1.0",                                         ║
║     features=[...],  // New features                          ║
║     fixes=[...]      // Bug fixes                             ║
║   )                                                             ║
║   → User-friendly changelog                                    ║
╚════════════════════════════════════════════════════════════════╝
```

---

## Implementation Details

### MCP Resource Prompt Endpoint

Each MCP should implement:

```typescript
interface ResourcePromptRequest {
  profile: "Development" | "QA" | "Security" | "DevOps" | "Product";
  session_context?: {
    session_objective?: string;
    repo_name?: string;
    recent_tools?: string[];
  };
}

interface ResourcePromptResponse {
  mcp_name: string;
  calling_profile: string;
  primary_resource_prompt: string;  // ASCII art + explanation
  quick_start: string[];             // 3-5 quick commands
  common_workflows: string[];        // Typical use cases
  learning_resources: string[];      // Links to docs
  related_mcps: string[];            // Other MCPs that help
  keyboard_shortcuts?: object;       // If applicable
}

// Usage in MCP:
export async function get_resource_prompt(req: ResourcePromptRequest): Promise<ResourcePromptResponse> {
  const profile = req.profile || detectProfile(req.session_context);
  
  const prompts = {
    "Development": PROMPT_DEV_ENGINEER,
    "QA": PROMPT_QA_MANAGER,
    "Security": PROMPT_SECURITY_OFFICER,
    "DevOps": PROMPT_DEVOPS_ENGINEER,
    "Product": PROMPT_PRODUCT_MANAGER
  };
  
  return {
    mcp_name: "qazilla-mcp",
    calling_profile: profile,
    primary_resource_prompt: prompts[profile],
    quick_start: [...],
    common_workflows: [...],
    learning_resources: [...],
    related_mcps: [...]
  };
}
```

### Integration with Claude Code

When a developer calls an MCP in Claude Code, the harness can:

1. Detect caller's profile (from session-mcp context)
2. Fetch resource prompt: `mcp.get_resource_prompt({profile: "Development"})`
3. Display prompt in sidebar before tool execution
4. Highlight recommended tools for this profile
5. Suggest common workflows

---

## Example Workflow: Feature Development with Profile-Based Prompts

### Day 1: Developer starts building

```
[Claude Code starts session]
├─ Detects: user_role = "developer"
├─ Session objective: "Implement user authentication"
│
├─ Dev calls: backzilla.analyze_backend_requirement()
│  └─ Gets prompt:
│     "Quick backend design. Focus on API contracts + data models.
│      Common: generate_fastapi_router() → generate_database_schema() → tests"
│
├─ Dev calls: qazilla.generate_unit_tests()
│  └─ Gets prompt:
│     "Quick test generation. Generate BEFORE implementation (TDD).
│      Then: qa-mcp.run_unit_tests() to verify.
│      Tip: Aim for >80% coverage."
│
├─ Dev implements code
│
└─ Dev calls: deploy-mcp.commit_files()
   └─ Gets prompt:
      "Auto-triggers CI. Wait for all checks to pass.
       If failed: Fix code + commit again. Keep iterating."
```

### Day 2-3: QA takes over

```
[QA Manager opens same branch in Claude Code]
├─ Detects: user_role = "qa_manager"
├─ Session objective: "QA & Release auth feature"
│
├─ QA calls: qazilla.create_test_plan()
│  └─ Gets prompt:
│     "Full QA toolkit. Complete workflow:
│      1. create_test_plan()
│      2. generate_scenarios('auth_flow')
│      3. run_e2e_tests()
│      4. record_results()
│      5. generate_quality_gate()
│      Target: >85% coverage, 100% pass rate before promotion."
│
├─ QA calls: pipeline-mcp.promote_service()
│  └─ Gets prompt:
│     "Release management. Workflow:
│      dev → homol (auto-deploy + smoke tests)
│      homol → prod (manual approval + blue-green)"
│
└─ QA calls: zilla-observatory (if ops team)
   └─ Gets prompt: "Monitor prod health post-release"
```

---

## Benefits

1. **Reduced Context Switching**: Profiles see only relevant tools
2. **Faster Onboarding**: New team members understand workflow immediately
3. **Fewer Mistakes**: Prompts guide best practices
4. **Better Collaboration**: Cross-functional teams understand each other's workflows
5. **Data-Driven**: Can measure adoption + effectiveness of prompts

---

## Metrics to Track

- **Prompt Effectiveness**: % of users who follow the suggested workflow
- **Tool Adoption**: % increase in tool usage after prompt introduction
- **Time-to-Productivity**: Reduction in onboarding time
- **Error Rate**: % of workflows that complete without issues
- **Profile Accuracy**: % of detected profiles that match user's actual role

---

