# Quality Gates System — Automated Release Gates

Sistema automático de gates que bloqueia/libera features para próximas fases.

## Propósito

- **Objective criteria** — gates não dependem de opinião, são métricas
- **Automation** — validação rápida, sem wait para human approval
- **Transparency** — cada gate mostra exatamente por que passou/falhou
- **Escalabilidade** — mesmos critérios aplicados a todas as features

## Gate Types

### 1. Architecture Review Gate
**Quando**: Depois que ArchZilla entregar blueprint
**Responsável**: ArchZilla + ai-governance-mcp
**Critérios**:
```
✓ ADR created and approved
✓ C4 diagrams complete
✓ API contract > 90% specified
✓ No unresolved dependencies
✓ Risk assessment completed
✓ Non-functional requirements addressed
✓ Technology stack approved
```
**Ação se falhar**: Bloqueado até resolução; comentário automático no PR

---

### 2. API Contract Validation Gate
**Quando**: API spec pronta
**Responsável**: ArchZilla + BackZilla
**Critérios**:
```
✓ OpenAPI spec valid (openapi-generator passes)
✓ All endpoints documented
✓ Request/response schemas complete
✓ Error codes defined (400, 401, 403, 404, 500, etc)
✓ Authentication method specified
✓ Rate limiting defined
✓ Backwards compatibility assessed
```
**Ação se falhar**: QAZilla não pode escrever testes até passar

---

### 3. Code Quality Gate
**Quando**: PR merged para develop
**Responsável**: BackZilla + qa-mcp
**Critérios**:
```
✓ Code coverage >= 80%
✓ No new critical vulnerabilities (SAST scan)
✓ Linting passes (ruff/eslint)
✓ Type checking passes (mypy/tsc)
✓ Dependency audit no vulnerabilities > high
✓ All error paths handled
✓ No hardcoded secrets/credentials
```
**Ação se falhar**: Bloqueado em PR; requer developer fix

---

### 4. Security Scan Gate
**Quando**: Code finalizado, antes de QAZilla
**Responsável**: SecZilla + qa-mcp
**Critérios**:
```
✓ SAST: no critical/high findings
✓ Dependency check: no unpatched vulnerabilities
✓ Container scan (Dockerfile): no critical layers
✓ IAM policy check: least privilege verified
✓ Secret scanning: no credentials detected
✓ Kubernetes manifest scan: security rules met
✓ API security: no auth bypass patterns
```
**Ação se falhar**: Feature bloqueada para staging; SecZilla must remediate

---

### 5. E2E Test Gate
**Quando**: Testes E2E executados
**Responsável**: QAZilla
**Critérios**:
```
✓ All E2E tests passing
✓ No flaky tests (retry < 2%)
✓ Test execution time < threshold
✓ All user journeys covered
✓ Error scenarios tested
✓ Accessibility tests passing
```
**Ação se falhar**: Feature stays in dev; retest until pass

---

### 6. API Test Gate
**Quando**: APIs implementadas e testadas
**Responsável**: QAZilla
**Critérios**:
```
✓ All endpoints tested (GET, POST, PUT, DELETE)
✓ Status codes correct (200, 400, 401, 404, 500)
✓ Response schemas validate
✓ Authentication works (token, JWT)
✓ Authorization enforced
✓ Error messages meaningful
✓ Rate limiting tested
✓ Pagination works
```
**Ação se falhar**: API not promoted; developer fixes failing tests

---

### 7. UI Accessibility Gate
**Quando**: FrontZilla UI complete
**Responsável**: QAZilla + axe-core
**Critérios**:
```
✓ WCAG 2.1 AA compliance
✓ Color contrast >= 4.5:1 (AA)
✓ All images have alt text
✓ Form labels accessible
✓ Keyboard navigation works
✓ Focus visible
✓ Screen reader compatible
✓ No automatic sound/video
```
**Ação se falhar**: UI not released; accessibility issues must be fixed

---

### 8. Performance Gate
**Quando**: Load testing complete
**Responsável**: OpsZilla + QAZilla
**Critérios**:
```
✓ API response time < SLA (e.g., 200ms p95)
✓ DB query time < threshold
✓ Memory usage < limit
✓ CPU usage under load < threshold
✓ Throughput >= minimum (e.g., 1000 req/s)
✓ Error rate under load < 0.1%
```
**Ação se falhar**: Feature requires optimization before release

---

### 9. Security Release Gate
**Quando**: Antes de merge para main/release
**Responsável**: SecZilla + QAZilla
**Critérios**:
```
✓ Threat model completed
✓ All high-risk threats mitigated
✓ Security test cases passing
✓ LGPD checklist completed (if applicable)
✓ Secrets rotation plan documented
✓ Incident response runbook created
✓ Security backlog items addressed
```
**Ação se falhar**: Release blocked; security must approve

---

### 10. Release Gate
**Quando**: Tudo pronto para produção
**Responsável**: POZilla
**Critérios**:
```
✓ All quality gates PASSED
✓ All tests PASSED (unit, integration, E2E, security, performance)
✓ All security issues RESOLVED
✓ All bugs marked FIXED (no critical/high open)
✓ Release notes prepared
✓ Deployment checklist completed
✓ Rollback plan documented
✓ Stakeholders notified
```
**Ação se falhar**: Release blocked until all criteria met

---

## Gate Configuration (gates.yaml)

```yaml
gates:
  architecture_review:
    enabled: true
    blocking: true
    approvers: ["archzilla"]
    timeout: 7d
    auto_retry: false
    criteria:
      - adr_created
      - c4_diagrams_complete
      - api_contract_> 90%
      - dependencies_resolved
      - risk_assessment_done
      - nfr_addressed
      - tech_stack_approved

  code_quality:
    enabled: true
    blocking: true
    criteria:
      - coverage >= 80
      - no_critical_vulns
      - linting_passes
      - type_check_passes
      - no_high_vulns_unpatched
      - error_handling_complete
      - no_hardcoded_secrets

  security_scan:
    enabled: true
    blocking: true
    auto_remediate: false
    criteria:
      - sast_no_critical
      - dependency_check_no_unpatched
      - container_scan_no_critical
      - iam_least_privilege
      - secret_scan_clean
      - k8s_security_rules
      - api_security_validated

  e2e_tests:
    enabled: true
    blocking: false
    timeout: 30m
    retry_flaky: true
    criteria:
      - all_tests_passing
      - flaky_rate < 2%
      - execution_time_ok
      - journeys_covered
      - error_scenarios_tested
      - accessibility_passing

  release:
    enabled: true
    blocking: true
    requires_approval: true
    criteria:
      - all_quality_gates_passed
      - all_tests_passed
      - all_security_resolved
      - no_critical_bugs_open
      - release_notes_ready
      - deployment_checklist_done
      - rollback_plan_documented
```

---

## Implementation

### Per-Gate System

Each gate is a standalone service/task that:
1. Checks criteria at regular intervals
2. Updates status (PENDING → PASSED/FAILED)
3. Sends notifications on state change
4. Provides detailed output on failure

### Integration Points

```
GitHub PR
    ↓
✓ Syntax checks (pre-commit hook)
    ↓
✓ Code Quality Gate (push to develop)
    ↓
✓ Security Scan Gate (pr created)
    ↓
✓ Architecture Review Gate (ArchZilla review)
    ↓
PR merged to develop
    ↓
✓ E2E Test Gate (QA environment)
✓ API Test Gate (API environment)
✓ Performance Gate (Load test environment)
    ↓
All gates PASSED
    ↓
Create release branch from develop
    ↓
✓ Security Release Gate (SecZilla final check)
✓ Release Gate (POZilla approval)
    ↓
Merge to main + deploy
```

## Monitoring & Alerts

**Dashboard shows**:
- Gate status for each feature (PENDING/PASSED/FAILED)
- Time in each gate (highlights blockers)
- Most common gate failures (trends)
- Features blocked (and why)

**Alerts**:
- Gate failure → Slack to responsible team
- Gate timeout → Escalation
- Multiple consecutive failures → Root cause analysis
