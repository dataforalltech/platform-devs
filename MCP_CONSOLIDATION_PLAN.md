# MCP Consolidation Plan: Detailed Implementation

**Date**: May 10, 2026  
**Priority**: P1 Testing + Security Consolidation  
**Timeline**: 4 weeks (May 13 - Jun 10)  
**Impact**: -2 MCPs, unified QA/testing context, -20% feature delivery time

---

## Executive Summary

This document provides week-by-week implementation tasks for consolidating:
1. **Testing MCPs** (qazilla + qa-mcp + test-mcp → qazilla)
2. **Security MCPs** (seczilla + qa-mcp security → seczilla)

No breaking changes. All MCPs remain operational during transition.

---

## Consolidation 1: Testing (qazilla + qa-mcp + test-mcp)

### Current Architecture

```
qazilla-mcp (20 tools)
├─ test_planning: analyze_quality_requirement, generate_test_plan, review_acceptance_criteria
├─ test_cases: generate_test_cases, generate_gherkin_scenarios, generate_e2e_tests, generate_api_tests
├─ automation: generate_unit_tests, generate_playwright_tests, generate_cypress_tests, ...
├─ bug_management: classify_bug_severity, generate_bug_report, validate_story_testability
└─ quality_gates: generate_quality_gate, generate_uat_checklist, review_test_coverage, ...

qa-mcp (15 tools)
├─ run_unit_tests (pytest/jest)
├─ run_e2e_tests (playwright)
├─ run_linter (ruff/eslint)
├─ run_security_scan (bandit/npm audit)
├─ run_type_check (mypy/tsc)
├─ check_accessibility (axe-core)
├─ check_dependencies (pip-audit)
├─ analyze_complexity (radon)
├─ get_coverage_report (coverage.json)
├─ run_api_tests (custom HTTP)
├─ visual_regression (pillow)
├─ check_doc_standards
├─ screenshot_page
└─ generate_qa_report

test-mcp (10 tools)
├─ create_test_plan
├─ add_scenario
├─ generate_scenarios (rest_api, react_component, auth_flow, ...)
├─ record_result
├─ run_checklist
├─ create_checklist
├─ get_test_plan
├─ get_validation_status
├─ list_test_plans
├─ double_check

TOTAL: 45 tools across 3 MCPs
```

### Target Architecture

```
qazilla-mcp (45 tools)
├─ Strategy & Planning (20 original tools)
│  ├─ analyze_quality_requirement
│  ├─ generate_test_plan
│  ├─ generate_test_cases
│  ├─ generate_gherkin_scenarios
│  └─ ... [20 original tools]
│
├─ Execution (15 wrapped qa-mcp tools)
│  ├─ run_unit_tests ← qa-mcp.run_unit_tests
│  ├─ run_e2e_tests ← qa-mcp.run_e2e_tests
│  ├─ run_linter ← qa-mcp.run_linter
│  ├─ run_security_scan ← qa-mcp.run_security_scan [WILL MOVE TO SECZILLA]
│  ├─ run_type_check ← qa-mcp.run_type_check
│  ├─ check_accessibility ← qa-mcp.check_accessibility
│  ├─ check_dependencies ← qa-mcp.check_dependencies [WILL MOVE TO SECZILLA]
│  └─ ... [remaining execution tools]
│
└─ Planning & Tracking (10 wrapped test-mcp tools)
   ├─ create_test_plan ← test-mcp.create_test_plan
   ├─ add_scenario ← test-mcp.add_scenario
   ├─ generate_scenarios ← test-mcp.generate_scenarios
   ├─ record_result ← test-mcp.record_result
   ├─ run_checklist ← test-mcp.run_checklist
   └─ ... [remaining planning tools]

RESULT: 45 tools, 1 MCP, unified QA domain
```

### Implementation Tasks

#### Week 1: Wrapper Foundation (May 13-17)

**Task 1.1: Create Tool Wrapper Layer in QAZilla**
- **Owner**: Backend engineer (BackZilla lead)
- **Time**: 8 hours
- **Steps**:
  1. Add new file: `qazilla-mcp-server/src/tools/qa_wrappers.ts`
  2. Implement wrapper functions:
     ```typescript
     export async function run_unit_tests(params: RunUnitTestsParams): Promise<Result> {
       // Call qa-mcp.run_unit_tests internally
       const qaClient = new QAMCPClient(QA_MCP_PORT);
       return await qaClient.run_unit_tests(params);
     }
     
     export async function run_e2e_tests(params: RunE2ETestsParams): Promise<Result> {
       // Call qa-mcp.run_e2e_tests internally
       const qaClient = new QAMCPClient(QA_MCP_PORT);
       return await qaClient.run_e2e_tests(params);
     }
     // ... repeat for all 15 qa-mcp tools
     ```
  3. Register wrappers in `TOOL_SCHEMAS`
  4. Add unit tests for each wrapper (3 tests per wrapper = 45 tests)

**Task 1.2: Create Tool Wrapper Layer for Test-MCP Tools**
- **Owner**: Backend engineer
- **Time**: 6 hours
- **Steps**:
  1. Add new file: `qazilla-mcp-server/src/tools/test_plan_wrappers.ts`
  2. Implement 10 wrapper functions (same pattern)
  3. Register in TOOL_SCHEMAS
  4. Add 30 unit tests

**Task 1.3: Update QAZilla Server Registration**
- **Owner**: DevOps (OpsZilla)
- **Time**: 2 hours
- **Steps**:
  1. Update `.mcp.json`: tools count 20 → 45
  2. Update server.ts: load both original + wrapper tool schemas
  3. Verify no port conflicts
  4. Update docs: new tools documented

**Deliverable**: PR with +300 lines (wrappers), +75 tests, ready for review

---

#### Week 2: Test-MCP Tools Integration (May 20-24)

**Task 2.1: Integrate Test-MCP Plan Management**
- **Owner**: QA engineer (QAZilla lead)
- **Time**: 8 hours
- **Steps**:
  1. Add to qazilla.db: new tables for test plans if not already present
  2. Verify test-mcp database compatibility
  3. Add migration: copy existing test plans schema to qazilla context
  4. Add tests: create_test_plan, add_scenario, record_result workflows
  5. Validate: Run full test suite

**Task 2.2: Integrate Test-MCP Checklist Management**
- **Owner**: QA engineer
- **Time**: 6 hours
- **Steps**:
  1. Add checklist table to qazilla.db
  2. Implement run_checklist wrapper (call test-mcp internally)
  3. Add workflow tests
  4. Verify checklist data model compatibility

**Task 2.3: Deprecation Roadmap for test-mcp**
- **Owner**: Documentation + Product Manager
- **Time**: 4 hours
- **Steps**:
  1. Create DEPRECATION.md in test-mcp/
  2. Document migration path: test-mcp → qazilla
  3. Email all consumers: "test-mcp will be deprecated in 3 months"
  4. Add warning logs to test-mcp APIs pointing to qazilla

**Deliverable**: Full integration of test-mcp tools into qazilla, +200 lines code, +50 tests

---

#### Week 3: QA-MCP Tools Integration (May 27-31)

**Task 3.1: Integrate QA Execution Tools (Non-Security)**
- **Owner**: QA engineer
- **Time**: 10 hours
- **Steps**:
  1. For each qa-mcp tool (except security ones):
     - Add wrapper in `qazilla-mcp-server/src/tools/qa_execution_wrappers.ts`
     - Test wrapper with real pytest/jest runs
     - Add workflow test: qazilla → run_unit_tests → parse output → record_result
  2. Tools to wrap:
     - run_unit_tests, run_e2e_tests, run_linter, run_type_check
     - check_accessibility, analyze_complexity, get_coverage_report
     - run_api_tests, visual_regression, screenshot_page
  3. Validate: All 10 execution tests pass

**Task 3.2: Security Tools → Move to SecZilla (Deferred)**
- **Owner**: Security engineer (SecZilla lead)
- **Time**: 0 hours (deferred to consolidation 2)
- **Note**: Mark as "will be moved to seczilla" in deprecation docs

**Task 3.3: Deprecate qa-mcp Public APIs**
- **Owner**: Documentation
- **Time**: 4 hours
- **Steps**:
  1. Create DEPRECATION.md in qa-mcp/
  2. Add warning messages to all public tools
  3. Document migration: qa-mcp.run_* → qazilla.run_*
  4. Keep qa-mcp internal (used by qazilla as backend)

**Deliverable**: Full integration of qa-mcp execution tools, 200+ lines, 100+ tests

---

#### Week 4: Testing & Finalization (Jun 3-7)

**Task 4.1: End-to-End Testing**
- **Owner**: QA lead + Developer
- **Time**: 8 hours
- **Steps**:
  1. **Scenario 1**: Feature development workflow using qazilla only
     - Dev: write code + qazilla.generate_unit_tests()
     - Dev: qazilla.run_unit_tests() [instead of qa-mcp]
     - QA: qazilla.create_test_plan() + qazilla.generate_e2e_tests()
     - QA: qazilla.run_e2e_tests() [instead of qa-mcp]
     - Result: Feature passes all gates
  2. **Scenario 2**: Release management workflow
     - QA: qazilla.generate_uat_checklist() + qazilla.run_checklist()
     - QA: qazilla.generate_quality_gate() → all passing
     - Result: Release approved
  3. **Scenario 3**: Quality metrics
     - Dev: qazilla.get_coverage_report()
     - Result: Coverage data fetched and displayed
  4. Verify: All workflows work, all tools callable

**Task 4.2: Performance Benchmarking**
- **Owner**: DevOps
- **Time**: 4 hours
- **Steps**:
  1. Measure: qazilla request latency vs. direct qa-mcp calls
     - Target: <10ms overhead per call
  2. Measure: Memory usage (qazilla + wrappers vs. separate MCPs)
  3. Report findings

**Task 4.3: Documentation & Migration Guide**
- **Owner**: Documentation engineer
- **Time**: 6 hours
- **Steps**:
  1. Create MIGRATION.md:
     - "From qa-mcp to qazilla" guide
     - Code examples for each migration
     - FAQ: Why consolidate?
  2. Update ARCHITECTURE_PROFILES_WORKFLOWS.md with new consolidated workflows
  3. Record 10-minute video: "Using QAZilla for all QA tasks"
  4. Update team onboarding materials

**Task 4.4: Deprecation Notices & Roadmap**
- **Owner**: Product Manager
- **Time**: 3 hours
- **Steps**:
  1. Email all teams: "qa-mcp & test-mcp deprecation timeline"
     - Timeline: 3 months deprecation period
     - By Sep 10: All consumers must migrate to qazilla
     - By Oct 10: qa-mcp & test-mcp removed from production
  2. Add to sprint planning: "Migrate from qa-mcp to qazilla"
  3. Create Jira epic: "QA Tool Consolidation" with child tasks

**Deliverable**: Full testing report, performance benchmarks, migration guide

---

### Consolidation 1 Success Criteria

✅ **Functional**:
- All 45 qazilla tools callable without errors
- 150+ unit tests passing (100% coverage of wrappers)
- 6+ E2E workflow tests passing

✅ **Performance**:
- qazilla.run_unit_tests latency < 50ms (including qa-mcp call)
- Memory footprint same as before consolidation

✅ **Adoption**:
- 3+ teams migrated from qa-mcp to qazilla
- 0 blocking issues reported
- Feedback: "Easier to use"

✅ **Documentation**:
- Migration guide reviewed by all team leads
- Onboarding video recorded
- FAQ covers top 10 questions

---

## Consolidation 2: Security (seczilla + qa-mcp security tools)

### Current Architecture

```
seczilla-mcp (20 tools)
├─ threat_modeling: generate_threat_model, map_security_risks, ...
├─ control_design: generate_security_controls, validate_against_standards, ...
├─ security_architecture: generate_security_architecture, ...
├─ penetration_testing: ...
├─ compliance: ...
└─ ... [20 security-focused tools]

qa-mcp (15 tools)
├─ run_security_scan (bandit/npm audit) ← MOVE TO SECZILLA
├─ check_dependencies (pip-audit) ← MOVE TO SECZILLA
├─ [13 other non-security tools]

ai-governance-mcp (14 tools)
├─ validate_contract
├─ validate_lib_change
├─ ecosystem validation
└─ ... [14 governance tools]

ISSUE:
  Security scanning (qa-mcp) is isolated from threat modeling (seczilla)
  Flow is broken: seczilla designs threats → qa-mcp scans → gap
```

### Target Architecture

```
seczilla-mcp (25 tools)
├─ threat_modeling: [20 original tools]
│  ├─ generate_threat_model
│  ├─ map_security_risks
│  ├─ ...
│
├─ scanning & validation: [5 new tools]
│  ├─ run_security_scan ← moved from qa-mcp
│  ├─ check_dependencies ← moved from qa-mcp
│  ├─ scan_dependency_risks
│  ├─ validate_threat_model
│  └─ validate_security_controls
│
└─ orchestration: call ai-governance for contract validation

ai-governance-mcp (14 tools)
├─ validate_contract (ecosystem contracts, not security)
├─ validate_lib_change (library changes, not security)
└─ ... [keep separate]

RESULT:
  Unified flow: threat model → generate controls → run scans → validate
  ai-governance stays separate (different domain)
```

### Implementation Tasks

#### Week 2: Security Consolidation Design (May 20-24)

**Task 2.1: Analyze Security Tool Dependencies**
- **Owner**: Security engineer (SecZilla lead)
- **Time**: 6 hours
- **Steps**:
  1. Map current usage: who calls run_security_scan, check_dependencies?
  2. Document dependency chain: threat_model → controls → scans
  3. Identify breaking risks (none expected, qa-mcp is backend)
  4. Create deprecation timeline for qa-mcp security tools

**Task 2.2: Design Security Tool Integration**
- **Owner**: Security engineer
- **Time**: 4 hours
- **Steps**:
  1. Design new seczilla tools:
     - `run_security_scan(repo_path, framework="auto")` → calls qa-mcp internally
     - `check_dependencies(repo_path)` → calls qa-mcp internally
     - `scan_dependency_risks(...)` → enhanced version with risk assessment
     - `validate_threat_model(threats, evidence)` → verify controls exist
  2. Document tool signatures
  3. Define success criteria for integration

---

#### Week 3: Security Integration Implementation (May 27-31)

**Task 3.1: Implement Security Scanning Wrappers**
- **Owner**: Security engineer
- **Time**: 10 hours
- **Steps**:
  1. Add file: `seczilla-mcp-server/src/tools/security_scanning.ts`
  2. Implement 5 new tools (wrappers + enhancements)
  3. Add database tables: security_scans, vulnerability_assessment
  4. Add 60 unit tests
  5. Verify: All scans run successfully

**Task 3.2: Integrate with Threat Model Database**
- **Owner**: Security engineer
- **Time**: 6 hours
- **Steps**:
  1. Add relationship: threat_model → controls → scans (in seczilla.db)
  2. Add query: get_threats_for_scan(repo_id) → returns relevant threats
  3. Add validation: verify all threats have corresponding controls + scans
  4. Add tests

**Task 3.3: Deprecate qa-mcp Security Tools**
- **Owner**: Documentation
- **Time**: 4 hours
- **Steps**:
  1. Update qa-mcp DEPRECATION.md: move security tools to seczilla by Oct 10
  2. Add warning to qa-mcp.run_security_scan: "Use seczilla.run_security_scan instead"
  3. Document migration path for security scans

---

#### Week 4: Security Testing & Finalization (Jun 3-7)

**Task 4.1: End-to-End Security Workflow Testing**
- **Owner**: Security engineer + Dev
- **Time**: 8 hours
- **Steps**:
  1. **Scenario 1**: Threat modeling + control validation
     - seczilla.generate_threat_model(app)
     - seczilla.generate_security_controls(threats)
     - seczilla.validate_security_controls() → verifies all controls defined
     - Result: Security review complete
  2. **Scenario 2**: Security scanning + validation
     - seczilla.run_security_scan(repo_path)
     - seczilla.validate_threat_model(threats, evidence)
     - Result: Threats matched with scan evidence
  3. **Scenario 3**: Dependency risk assessment
     - seczilla.check_dependencies(repo_path)
     - seczilla.scan_dependency_risks()
     - Result: Risk ratings assigned
  4. Verify: All workflows work end-to-end

**Task 4.2: Cross-Validation with ai-governance**
- **Owner**: Governance engineer
- **Time**: 4 hours
- **Steps**:
  1. Verify: seczilla doesn't duplicate ai-governance contract validation
  2. Document: Clear boundary
     - seczilla: threat & vulnerability management
     - ai-governance: ecosystem contracts & governance
  3. Add integration test: seczilla → calls ai-governance for contract validation
  4. Result: No overlap, clear domain separation

**Task 4.3: Security Documentation**
- **Owner**: Security engineer
- **Time**: 6 hours
- **Steps**:
  1. Create SECURITY_WORKFLOW.md: Complete security workflow using seczilla
  2. Update threat modeling template: Now includes scanning + control validation
  3. Create security ADR: "Consolidated threat → control → scan flow"
  4. Training: 15-minute video on new security consolidation

**Task 4.4: Rollout Communication**
- **Owner**: Security lead + Product Manager
- **Time**: 3 hours
- **Steps**:
  1. Email security team: New workflow + benefits
  2. Schedule training session
  3. Create Jira epic: "Security Tool Consolidation"

---

### Consolidation 2 Success Criteria

✅ **Functional**:
- All 25 seczilla tools callable without errors
- 100+ unit tests passing
- 4+ E2E security workflows passing

✅ **Integration**:
- Threat model → controls → scans flow working
- No overlap with ai-governance
- Clear domain boundary

✅ **Adoption**:
- Security team trained on new workflow
- 0 blocking issues
- Feedback: "More cohesive threat→control→scan journey"

---

## Rollback Strategy (If Issues Arise)

### For Testing Consolidation:

1. **If qazilla wrapper fails**:
   - Revert: qazilla commit
   - Fallback: Teams continue using qa-mcp + test-mcp separately
   - No breaking changes (wrappers are additive)

2. **If qa-mcp deprecation causes issues**:
   - Keep qa-mcp in production (don't remove)
   - Both qa-mcp + qazilla coexist
   - Migrate teams gradually (no forced deadline)

### For Security Consolidation:

Same approach: wrappers are additive, fallback is easy.

---

## Timeline Summary

| Week | Task | Owner | Deliverable |
|------|------|-------|-------------|
| W1 (May 13-17) | Wrapper foundation | Backend | +300 lines, +75 tests |
| W2 (May 20-24) | Test-MCP integration + Security design | QA + Security | +200 lines, +50 tests, design doc |
| W3 (May 27-31) | QA-MCP integration + Security implementation | QA + Security | +500 lines, +200 tests, +100 lines security |
| W4 (Jun 3-7) | E2E testing, docs, rollout | QA + Docs + Product | Testing report, migration guides, training |

**Total**: 4 weeks, 2 consolidations, -2 MCPs, unified QA + security domains

---

## Post-Consolidation Metrics

### Before Consolidation:

- **Tools**: 350+ across 45 MCPs
- **Team Context Switching**: Dev team averages 8 MCP hops per session
- **Tool Duplication**: 40+ overlapping tools
- **Feature Delivery**: Average 4 weeks (design to prod)
- **QA Onboarding**: 2 weeks (learn 3 MCPs)

### After Consolidation (Target):

- **Tools**: 330+ across 43 MCPs (-2 MCPs)
- **Team Context Switching**: Dev team averages <5 MCP hops per session (-37%)
- **Tool Duplication**: <5 overlapping tools (-87%)
- **Feature Delivery**: Average 3.2 weeks (-20% from tool consolidation)
- **QA Onboarding**: 1 week (learn 1 MCP)

---

## Budget & Resource Planning

### Week 1: Wrapper Foundation
- **Backend Engineer**: 8 hours (wrapper code)
- **DevOps/SRE**: 2 hours (setup)
- **Total**: 10 hours = 1.25 person-days

### Week 2: Integration + Design
- **QA Engineer**: 14 hours (test-mcp integration)
- **Security Engineer**: 10 hours (security design)
- **Documentation**: 4 hours (deprecation)
- **Total**: 28 hours = 3.5 person-days

### Week 3: Full Integration
- **QA Engineer**: 10 hours (qa-mcp integration)
- **Security Engineer**: 10 hours (security scanning)
- **Documentation**: 4 hours (deprecation)
- **Total**: 24 hours = 3 person-days

### Week 4: Testing & Rollout
- **QA Lead**: 8 hours (E2E testing)
- **DevOps**: 4 hours (perf testing)
- **Documentation**: 6 hours (guides)
- **Product Manager**: 3 hours (communication)
- **Security Lead**: 4 hours (training)
- **Total**: 25 hours = 3.1 person-days

**Grand Total**: 87 hours = 11 person-days across 4 weeks

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| qa-mcp latency overhead | Low | Benchmark <10ms, use async calls |
| Breaking changes in qa-mcp | Low | Only wrappers are additive |
| Teams resist migration | Medium | Training + clear benefits communication |
| Test coverage gaps | Low | 150+ unit tests ensure completeness |
| Performance regression | Low | Benchmark + load testing |

---

## Success Criteria Checklist

- [ ] All 45 qazilla tools functional
- [ ] <10ms wrapper latency overhead
- [ ] 150+ new unit tests passing
- [ ] 6+ E2E workflows tested
- [ ] 3+ teams migrated from qa-mcp
- [ ] Security scanning integrated
- [ ] Migration guide published
- [ ] 0 blocking production issues
- [ ] Team feedback: "Easier to use"
- [ ] Feature delivery time -20%

---

