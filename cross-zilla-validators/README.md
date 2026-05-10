# Cross-Zilla Validators — MCP Integration Chains

Validações automáticas que Zillas fazem um do outro antes de handoff.

## Propósito

- **Catch integration issues early** — antes de passar para próximo Zilla
- **Enforce contracts** — APIcontract deve estar validado antes do BackZilla implementar
- **Risk propagation** — SecZilla risks devem ser considerados por QAZilla
- **Dependency validation** — Garantir que dependências foram definidas corretamente

## Validation Chains

### 1. ProductZilla → POZilla
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
    ↓ POZilla ready to plan sprint
```

### 2. ArchZilla → BackZilla + OpsZilla
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
    ↓ BackZilla/OpsZilla ready to implement
```

### 3. BackZilla → QAZilla
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
    ↓ QAZilla ready to write E2E tests
```

### 4. FrontZilla → QAZilla
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
    ↓ QAZilla ready to test UI
```

### 5. SecZilla → All Zillas
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
        → BackZilla: "Use parameterized queries"
        → OpsZilla: "Enable WAF"
        → QAZilla: "Add injection tests"
```

### 6. All Zillas → QAZilla
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
    ↓ QAZilla ready for full test execution
```

### 7. QAZilla → POZilla (Release Gate)
```
Test Results
    ↓ validate_release_readiness()
        • All tests passing? ✓
        • No critical bugs open? ✓
        • Performance benchmarks met? ✓
        • Security scan passed? ✓
    ↓ POZilla: "Go/No-Go" decision
```

## Implementation Pattern

```typescript
// Exemplo: BackZilla calls ArchZilla validator
const architectureValidator = await mcpClient.call('cross-zilla-validators', 'validate_api_contracts', {
  feature: 'User Authentication',
  api_spec: myApiContract,
  architecture_spec: getFromArchZilla(),
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
✓ **Knowledge transfer** — validators document what each Zilla expects
✓ **Quality gate** — objective validation, not subjective review
