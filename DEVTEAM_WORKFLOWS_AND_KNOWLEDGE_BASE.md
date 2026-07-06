# DevTeam Workflows & Knowledge Base

## Mapa de Orquestração

```
Product-Manager (Entrada)
    ↓
Product-Owner (Planejamento do Backlog)
    ↓
┌─────────────────────────────────────────────────────────┐
│ Paralelo: Architecture + Frontend + Backend + DevOps │
└─────────────────────────────────────────────────────────┘
    ↓
Security (Validação de Segurança)
    ↓
QA-Engineer (Testes & Validação)
    ↓
Product-Owner (Orquestração de Release)
```

---

## 1. Product-Manager — Estratégia de Produto

### Workflow
```
Demanda de Negócio
    → analyze_product_problem
    → define_product_vision
    → map_user_personas
    → map_user_journey
    → calculate_rice_score
    → prioritize_backlog
    → define_mvp_scope
    → generate_release_plan
    → generate_handoff_to_engineering
    → Feature Spec para Product-Owner
```

### Inputs
- Demanda de negócio / OKRs
- Dados de usuários / market research
- Roadmap existente
- Constraints de negócio (budget, timeline)

### Outputs
- Epic + Feature specs
- User personas + journeys
- Acceptance criteria
- MVP scope definition
- Release plan
- Handoff document para arquitetura

### Base de Conhecimento
- **Docs**: Product strategy docs, user research, market analysis
- **Frameworks**: RICE scoring, MoSCoW prioritization, Jobs to be Done
- **Referências**: OKRs da plataforma, roadmap atual, histórico de releases
- **Padrões**: Definition of Ready (DoR) para features

---

## 2. Product-Owner — Orchestração de Plataforma

### Workflow
```
Feature Spec (Product-Manager)
    → analyze_business_demand
    → generate_epic
    → generate_feature_breakdown
    → map_dependencies
    → identify_scope_risks
    → prioritize_backlog_items
    → prepare_sprint_backlog
    → Parallelization Decision
        → Architecture (design)
        → Frontend (ui design)
        → Backend (implementation)
        → DevOps (infra planning)
    → Sync Points (integrações entre DevTeam)
    → generate_jira_tasks
    → validate_story_readiness
    → Handoff para QA-Engineer
```

### Inputs
- Feature specifications (Product-Manager)
- Constraints técnicas / infra
- Capacidade do time
- Roadmap / timeline

### Outputs
- Epic com user stories
- Sprint backlog
- Task assignments por DevTeam
- Dependency map
- Risk assessment
- Jira structure

### Base de Conhecimento
- **Docs**: Capacity planning, team structure, sprint templates
- **Frameworks**: Agile, SAFe, dependency mapping
- **Referências**: Historical velocity, resource availability, constraints
- **Padrões**: Definition of Done (DoD), Sprint ceremonies

---

## 3. Architecture — Design de Arquitetura

### Workflow
```
Feature Spec (Product-Owner)
    → analyze_architecture_requirement
    → define_bounded_contexts
    → define_system_modules
    → define_non_functional_requirements
    → generate_c4_diagram
    → generate_solution_blueprint
    → generate_adr (Architecture Decision Record)
    → generate_api_guidelines
    → define_integration_strategy
    → generate_event_contracts
    → map_architecture_risks
    → generate_technical_roadmap
    → review_architecture
    → Handoff para Backend + DevOps
```

### Inputs
- Feature specification (Product-Owner)
- Current architecture state
- Non-functional requirements
- Integration points com outros serviços
- Constraints de infraestrutura

### Outputs
- Architecture blueprint (C4 diagrams)
- API contracts
- Event schemas
- Technical roadmap
- ADRs (Architecture Decisions)
- Integration strategy
- Risk assessment

### Base de Conhecimento
- **Docs**: Current system architecture, service catalog, API inventory
- **Frameworks**: DDD (Domain-Driven Design), C4 Model, SOLID principles
- **Referências**: ecosystem.yaml, service dependencies, historical ADRs
- **Padrões**: API design standards, event-driven patterns, microservice patterns
- **Integrações MCP**: ai-governance-mcp (create_adr), qa-mcp (run_linter)

---

## 4. Frontend — Design & UI

### Workflow
```
Feature Spec (Product-Owner) + Architecture (Architecture)
    → analyze_requirement
    → map_user_personas
    → map_user_journey
    → generate_wireframe
    → generate_screen_brief
    → suggest_ui_components
    → create_design_tokens
    → generate_component_spec
    → generate_component_variants
    → map_visual_states
    → generate_ux_writing
    → validate_visual_accessibility
    → Handoff para Backend (API specs) + Frontend Dev
```

### Inputs
- Feature specification (Product-Owner)
- User personas + journeys
- Design system / brand guidelines
- API contracts (Architecture)
- Accessibility requirements

### Outputs
- Wireframes
- High-fidelity designs
- Component specifications
- Design tokens
- UX writing (microcopy)
- Accessibility validation
- Design system updates

### Base de Conhecimento
- **Docs**: Design system, component library, brand guidelines
- **Frameworks**: WCAG 2.1, design thinking, UX patterns
- **Referências**: Figma design files, component inventory, user research
- **Padrões**: Design patterns, accessibility guidelines, responsive design standards

---

## 5. Backend — Backend Development

### Workflow
```
Feature Spec (Product-Owner) + Architecture (Architecture) + UI (Frontend)
    → analyze_backend_requirement
    → generate_api_contract
    → generate_database_schema
    → generate_repository_layer
    → generate_service_layer
    → generate_fastapi_router (ou NestJS controller)
    → generate_auth_policy
    → generate_migration
    → generate_backend_tests
    → map_integration_flow
    → optimize_query
    → review_backend_code
    → Handoff para DevOps + QA-Engineer
```

### Inputs
- Architecture blueprint (Architecture)
- API specifications
- Database schema requirements
- Authentication/authorization requirements
- Integration endpoints
- Feature specification

### Outputs
- API contracts + OpenAPI specs
- Database schemas + migrations
- Service layer implementation
- Authentication policies
- Unit & integration tests
- Code review feedback
- Performance optimizations

### Base de Conhecimento
- **Docs**: API standards, database best practices, auth patterns, code style guide
- **Frameworks**: FastAPI, NestJS, SQLAlchemy, Pydantic, Zod
- **Referências**: Existing API endpoints, database state, service patterns
- **Padrões**: REST conventions, error handling, logging standards, transaction patterns
- **Integrações MCP**: qa-mcp (run_unit_tests, run_linter, run_security_scan)

---

## 6. DevOps — Infrastructure & Operations

### Workflow
```
Architecture (Architecture) + Deployment Plan (Product-Owner)
    → analyze_infrastructure_requirement
    → generate_dockerfile
    → generate_terraform_module
    → generate_kubernetes_manifest
    → generate_helm_chart
    → generate_iam_policy
    → generate_secret_strategy
    → generate_observability_plan
    → generate_github_actions_pipeline
    → generate_release_checklist
    → review_cloud_security
    → review_devops_config
    → Handoff para Security + QA-Engineer
```

### Inputs
- Architecture specifications (Architecture)
- Service dependencies
- Scale requirements
- High availability needs
- Security requirements
- Cost constraints
- Deployment strategy

### Outputs
- Dockerfiles + images
- Terraform modules
- Kubernetes manifests
- IAM policies
- Secret management strategy
- Observability stack (Prometheus, Grafana, etc.)
- CI/CD pipelines
- Release checklist

### Base de Conhecimento
- **Docs**: Infrastructure as Code, deployment patterns, runbooks, incident response plans
- **Frameworks**: Terraform, Kubernetes, Docker, Helm, GitHub Actions
- **Referências**: Current infrastructure state, cloud account structure, resource quotas
- **Padrões**: High availability patterns, disaster recovery, scaling strategies
- **Integrações MCP**: infra-mcp (terraform_validate, terraform_plan, policy_scan_checkov)

---

## 7. Security — Security & Compliance

### Workflow
```
All Artifacts (Architecture + Backend + DevOps + Frontend)
    → analyze_security_requirement
    → generate_threat_model
    → map_attack_surface
    → classify_security_risks
    → review_secure_code (Backend code)
    → review_api_security (API contracts)
    → review_auth_policy (Auth implementation)
    → generate_security_controls
    → review_iam_policy (DevOps policies)
    → review_cloud_security (Infrastructure)
    → review_kubernetes_security (K8s configs)
    → review_dockerfile_security (Container security)
    → generate_lgpd_checklist
    → map_sensitive_data
    → scan_dependency_risks
    → generate_devsecops_pipeline
    → generate_security_backlog
    → generate_incident_response_runbook
    → generate_security_release_checklist
    → Handoff para QA-Engineer (security test cases)
```

### Inputs
- All architectural artifacts
- API specifications
- Infrastructure code
- Source code (for SAST)
- Dependencies list
- Compliance requirements (LGPD, SOC2, etc.)

### Outputs
- Threat models + risk assessment
- Security control recommendations
- Vulnerability reports
- SAST/DAST findings
- LGPD compliance checklist
- IAM policy review
- Security test cases
- Incident response runbooks
- Security backlog (P1/P2/P3)

### Base de Conhecimento
- **Docs**: Security policies, threat models, compliance frameworks
- **Frameworks**: STRIDE, OWASP Top 10, CIS Benchmarks, LGPD, SOC2
- **Referências**: Known vulnerabilities, CVE database, security standards
- **Padrões**: Encryption standards, secret management, authentication patterns
- **Integrações MCP**: qa-mcp (run_security_scan), infra-mcp (policy_scan_checkov), ai-governance-mcp (validate_agent_decision)

---

## 8. QA-Engineer — Quality Assurance & Testing

### Workflow
```
Feature Spec (Product-Owner) + All Implementation Artifacts
    → analyze_quality_requirement
    → generate_test_plan
    → review_acceptance_criteria
    → generate_test_cases
    → generate_gherkin_scenarios
    → generate_e2e_tests (Frontend + Backend)
    → generate_api_tests (Backend APIs)
    → generate_unit_tests (Backend code)
    → generate_playwright_tests (Frontend)
    → generate_cypress_tests (Frontend)
    → generate_postman_collection (APIs)
    → generate_regression_suite
    → generate_smoke_test_suite
    → classify_bug_severity (for Security findings)
    → generate_bug_report
    → validate_story_testability
    → generate_quality_gate
    → generate_uat_checklist
    → review_test_coverage
    → generate_k6_performance_test
    → generate_security_test_cases (from Security threat model)
    → Execution & Validation
    → Release Gate
```

### Inputs
- Feature specifications + acceptance criteria
- Implementation code (Backend)
- UI designs (Frontend)
- API contracts (Architecture)
- Security threat models (Security)
- Infrastructure configs (DevOps)

### Outputs
- Test plan + test cases
- Gherkin scenarios
- Automated test suites (unit, integration, E2E, API, performance)
- Test coverage reports
- Bug reports + severity classifications
- UAT checklist
- Quality gates + release criteria
- Performance test results

### Base de Conhecimento
- **Docs**: Test strategies, test data, testing standards, quality metrics
- **Frameworks**: Playwright, Cypress, Jest, Vitest, Pytest, Postman, k6
- **Referências**: Historical bug patterns, test metrics, coverage baselines
- **Padrões**: Testing pyramid, shift-left testing, Definition of Done (testing aspects)
- **Integrações MCP**: qa-mcp (run_unit_tests, run_linter, run_security_scan, check_accessibility), test-mcp (create_test_plan)

---

## Matriz de Dependências

```
Product-Manager
    ↓
Product-Owner (orquestra)
    ├→ Architecture ──────────┐
    ├→ Backend ─────────┼─→ Security ──→ QA-Engineer ──→ Release
    ├→ Frontend ────────┤
    └→ DevOps ──────────┘
```

---

## Fluxo de Informação (MCP Calls)

### Architecture → Backend
- API contracts
- Database schema requirements
- Service boundaries

### Architecture → DevOps
- Infrastructure requirements
- Scalability needs
- High availability patterns

### Backend → QA-Engineer
- API endpoints for testing
- Integration points
- Error scenarios

### Frontend → QA-Engineer
- UI screens/flows
- Interaction patterns
- Accessibility requirements

### Security → QA-Engineer
- Threat models
- Security test scenarios
- Compliance requirements

### All DevTeam → Product-Owner
- Status updates
- Risk identifications
- Timeline adjustments

---

## Base de Conhecimento Centralizada

### 1. **ecosystem.yaml** (Governança)
- Mapeamento de serviços
- Dependências entre serviços
- Proprietários (team)
- Ports
- Status (active, deprecated)
- Contracts (API, event, database)

### 2. **AGENTS.md** (Trinity Pattern)
- Responsabilidades de cada DevTeam
- Explícitos NÃO-responsabilidades
- Escalas de complexidade aceitas
- Padrões de decisão

### 3. **Design System** (Frontend)
- Component library
- Design tokens
- Brand guidelines
- Accessibility standards

### 4. **API Standards** (Architecture + Backend)
- REST conventions
- Error handling
- Versioning strategy
- OpenAPI specification

### 5. **Security Policies** (Security)
- Encryption standards
- Authentication patterns
- Authorization rules
- Compliance frameworks

### 6. **Infrastructure as Code** (DevOps)
- Terraform modules
- Kubernetes configs
- CI/CD templates
- Runbooks

### 7. **Testing Standards** (QA-Engineer)
- Test pyramid
- Coverage targets
- Test data strategies
- Definition of Done

### 8. **Product Roadmap** (Product-Manager)
- Vision & mission
- OKRs
- Feature priorities
- Release calendar

---

## Checkpoints & Gates

| Fase | Gate | Responsável | Critério |
|------|------|-------------|----------|
| Design | Architecture Review | Architecture | ADR approved, risk assessment done |
| Design | API Contract Review | Backend + Architecture | OpenAPI spec validated |
| Design | Security Design Review | Security | Threat model completed, risks mitigated |
| Implementation | Code Review | Backend | All security rules passed, tests > 80% coverage |
| Implementation | Security SAST | Security | No critical/high vulnerabilities |
| Implementation | API Test Gate | QA-Engineer | All API tests passing |
| Pre-Release | Security Scan | Security | Dependency scan passed |
| Pre-Release | E2E Test Gate | QA-Engineer | All E2E tests passing |
| Pre-Release | Performance Gate | QA-Engineer + DevOps | Performance benchmarks met |
| Pre-Release | Security Release Check | Security | Security checklist passed |
| Release | Go/No-Go | Product-Owner | All gates passed, release approved |

---

## Exemplo: Feature "User Authentication with OAuth2"

### Product-Manager Phase
- **Input**: Business requirement "Enable social login"
- **Output**: Feature spec with user stories, acceptance criteria, RICE score
- **Time**: 2-3 days

### Product-Owner Phase
- **Input**: Feature spec
- **Output**: Epic breakdown, sprint planning, team assignments
- **Time**: 1 day

### Parallel Phase (Days 1-7)

**Architecture**
- Threat model for OAuth2 flow
- API contract design
- Integration strategy with OAuth provider

**Backend**
- Implement OAuth2 flow
- User database schema
- Token management

**Frontend**
- Login page design
- OAuth button placement
- Error state designs

**DevOps**
- OAuth provider configuration
- Secret management for OAuth credentials
- Monitoring for auth failures

### Security Phase (Day 8)
- Review OAuth2 implementation
- Validate token handling
- Check LGPD compliance for user data
- Generate security test cases

### QA-Engineer Phase (Day 9-10)
- Test happy path + error scenarios
- Test token expiration/refresh
- E2E test full flow
- Security testing (token injection, session hijacking)

### Release Phase (Day 11)
- Product-Owner orchestrates go/no-go decision
- All gates must pass

---

## Próximos Passos

1. **Criar knowledge-base MCP** — Centralizar documentação que DevTeam consultam
2. **Implementar cross-DevTeam calls** — MCPs se chamam para validações cruzadas
3. **Setup automation** — Gates automáticos, CI/CD gates
4. **Training materials** — Docs para cada DevTeam explicando seu role
5. **Metrics & observability** — Dashboard de saúde do ecossistema DevTeam
