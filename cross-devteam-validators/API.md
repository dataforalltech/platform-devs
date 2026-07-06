# Cross-DevTeam Validators — Phase 2

**Port**: 7111  
**Database**: `validators.db`  
**Status**: Fully implemented with 18 validators across 6 categories

## Overview

The Cross-DevTeam Validators MCP ensures quality and consistency when handing off work between different DevTeam (specialized AI agents). It validates outputs at each stage of the product development lifecycle.

## Validator Categories

### Product Validators (3)
1. **validate_feature_completeness** — Ensures features have all required components
2. **validate_epic_breakdown** — Validates epic decomposition into stories
3. **validate_acceptance_criteria** — Ensures AC is testable and clear

### Architecture Validators (3)
4. **validate_api_contracts** — Validates OpenAPI specs and schemas
5. **validate_database_schema** — Ensures DB design follows standards
6. **validate_integration_points** — Validates service integration contracts

### Backend Validators (3)
7. **validate_code_testability** — Ensures code is unit-testable
8. **validate_api_compliance** — Validates endpoint implementation
9. **validate_test_coverage** — Ensures coverage > 80%

### Frontend Validators (3)
10. **validate_accessibility** — WCAG 2.1 AA compliance
11. **validate_design_system_usage** — Ensures design consistency
12. **validate_responsive_design** — Mobile/tablet/desktop coverage

### Security Validators (2)
13. **validate_threat_model_completeness** — OWASP coverage
14. **validate_against_standards** — Security standards compliance

### Quality Validators (3)
15. **validate_readiness_for_testing** — Pre-QA validation
16. **validate_test_plan_coverage** — Test scenario completeness
17. **validate_release_readiness** — Release criteria checklist
18. **check_governance** — Cross-cutting governance compliance

## Handoff Validation Flow

```
DevTeam A Output → Validators → Validation Rules → DevTeam B Input
                    ↓
              validation_results table
                    ↓
              Governance compliance check
```

## Database Schema

**Tables:**
- `validation_results` — records of each validation run
- `validator_rules` — rule sets per DevTeam boundary
- `validation_history` — audit trail of all validations

## Tool Methods

### validate_handoff(from_devteam, to_devteam, handoff_data)
Validates a complete handoff between two DevTeam.

**Input:**
```typescript
{
  from_devteam: string;
  to_devteam: string;
  handoff_data: Record<string, unknown>;
}
```

**Output:**
```typescript
{
  from: string;
  to: string;
  valid: boolean;
  errors: string[];
}
```

### check_governance(devteam_name, check_type?)
Validates governance compliance for a DevTeam.

### validate_output(devteam_name, output)
Validates DevTeam output against expected schema.

### get_validation_rules(from_devteam, to_devteam)
Retrieves validation rules for a specific handoff.

## Testing

**Coverage**: 40+ test cases
- Handoff validation
- Governance checks
- Output schema validation
- Rule retrieval

## Integration Points

- **Input**: Knowledge Base MCP (standards reference)
- **Output**: Quality Gates System (validation results)
- **Consumed by**: Quality Gates, Observatory dashboards
