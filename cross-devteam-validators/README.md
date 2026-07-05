# Cross-DevTeam Validators — MCP Integration Chains

Validações automáticas que DevTeam fazem um do outro antes de handoff.

## Propósito

- **Catch integration issues early** — antes de passar para próximo DevTeam
- **Enforce contracts** — APIcontract deve estar validado antes do Backend implementar
- **Risk propagation** — Security risks devem ser considerados por QA-Engineer
- **Dependency validation** — Garantir que dependências foram definidas corretamente

## Validation Chains

### 1. Product-Manager → Product-Owner
```
Feature Spec
    ↓ validate_feature_completeness()
        • Acceptance criteria defined? ✓
        • Success metrics defined? ✓
        • MVP scope clear? ✓
    ↓ validate_epic_breakdown()
        • Stories have capacity estimates? ✓
        • Dependencies identified? ✓
        • Risks documented? ✓
    ↓ Product-Owner ready to plan sprint
```

### 2. Architecture → Backend + DevOps
```
Architecture Blueprint
    ↓ validate_api_contracts()
        • All endpoints specified? ✓
        • Request/response schemas complete? ✓
        • Error codes defined? ✓
    ↓ validate_database_schema()
        • Tables identified? ✓
        • Relationships correct? ✓
        • Migrations planned? ✓
    ↓ validate_integration_points()
        • External APIs defined? ✓
        • Event contracts specified? ✓
    ↓ Backend/DevOps ready to implement
```

### 3. Backend → QA-Engineer
```
Implementation
    ↓ validate_code_testability()
        • Functions have single responsibility? ✓
        • Error handling comprehensive? ✓
        • Mocking points identified? ✓
    ↓ validate_api_compliance()
        • Matches architecture contract? ✓
        • Error responses consistent? ✓
        • Auth/rate-limit implemented? ✓
    ↓ validate_test_coverage()
        • Coverage > 80%? ✓
        • All error paths tested? ✓
    ↓ QA-Engineer ready to write E2E tests
```

### 4. Frontend → QA-Engineer
```
UI Implementation
    ↓ validate_accessibility()
        • All images have alt text? ✓
        • Keyboard navigation works? ✓
        • Color contrast WCAG AA? ✓
    ↓ validate_design_system_usage()
        • Using approved components? ✓
        • Spacing matches tokens? ✓
        • Typography consistent? ✓
    ↓ validate_responsive_design()
        • Mobile: working? ✓
        • Tablet: working? ✓
        • Desktop: working? ✓
    ↓ QA-Engineer ready to test UI
```

### 5. Security → All DevTeam
```
Security Review
    ↓ validate_threat_model_completeness()
        • STRIDE threats identified? ✓
        • Risk scores assigned? ✓
        • Mitigations proposed? ✓
    ↓ validate_against_standards()
        • OWASP Top 10 covered? ✓
        • LGPD requirements met? ✓
        • CIS Benchmarks aligned? ✓
    ↓ broadcast_security_requirements()
        → Backend: "Use parameterized queries"
        → DevOps: "Enable WAF"
        → QA-Engineer: "Add injection tests"
```

### 6. All DevTeam → QA-Engineer
```
All Implementation Artifacts
    ↓ validate_readiness_for_testing()
        • Architecture documented? ✓
        • API contracts finalized? ✓
        • Security requirements clear? ✓
        • Performance baselines set? ✓
    ↓ validate_test_plan_coverage()
        • All user stories have test cases? ✓
        • All APIs have test scenarios? ✓
        • All security risks tested? ✓
    ↓ QA-Engineer ready for full test execution
```

### 7. QA-Engineer → Product-Owner (Release Gate)
```
Test Results
    ↓ validate_release_readiness()
        • All tests passing? ✓
        • No critical bugs open? ✓
        • Performance benchmarks met? ✓
        • Security scan passed? ✓
    ↓ Product-Owner: "Go/No-Go" decision
```

## Implementation Pattern

```typescript
// Exemplo: Backend calls Architecture validator
const architectureValidator = await mcpClient.call('cross-devteam-validators', 'validate_api_contracts', {
  feature: 'User Authentication',
  api_spec: myApiContract,
  architecture_spec: getFromArchitecture(),
});

if (!architectureValidator.passed) {
  throw new Error(`API contract mismatch: ${architectureValidator.issues}`);
}

// Proceed with implementation
implementBackend(myApiContract);
```

## Validator Tools (MCP)

### Product Validators
- `validate_feature_completeness(feature_spec)` → { passed, issues }
- `validate_epic_breakdown(epic)` → { passed, complexity_assessment }
- `validate_acceptance_criteria(criteria_list)` → { passed, testability_score }

### Architecture Validators
- `validate_api_contracts(spec, reference)` → { passed, inconsistencies }
- `validate_database_schema(schema, constraints)` → { passed, issues }
- `validate_integration_points(integrations)` → { passed, missing_contracts }

### Backend Validators
- `validate_code_testability(code, language)` → { passed, suggestions }
- `validate_api_compliance(implementation, contract)` → { passed, violations }
- `validate_test_coverage(code, coverage_report)` → { passed, coverage_score }

### Frontend Validators
- `validate_accessibility(ui_code, design_spec)` → { passed, violations }
- `validate_design_system_usage(components, design_system)` → { passed, inconsistencies }
- `validate_responsive_design(screenshots, breakpoints)` → { passed, issues }

### Security Validators
- `validate_threat_model_completeness(model)` → { passed, gaps }
- `validate_against_standards(artifact, standard)` → { passed, violations }
- `broadcast_security_requirements(requirements, targets)` → { notified }

### Quality Validators
- `validate_readiness_for_testing(artifacts)` → { passed, missing }
- `validate_test_plan_coverage(test_plan, feature_spec)` → { passed, gaps }
- `validate_release_readiness(test_results)` → { passed, blockers }

## Benefits

✓ **Early detection** — issues caught before handoff, not after
✓ **Standards enforcement** — all artifacts conform to company standards
✓ **Time saved** — no rework, no delays in integration
✓ **Knowledge transfer** — validators document what each DevTeam expects
✓ **Quality gate** — objective validation, not subjective review
