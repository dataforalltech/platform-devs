# MCP Tools — Reconciliação (mapa de design × deployado) e Backlog de Organização

> Fonte-de-verdade viva: `TOOLS_LIVE_INVENTORY.csv` (gerado do `/mcp/tools/list` do gateway).
> Mapa de design: `TOOLS_DEPENDENCY_MATRIX.csv` (278 tools).
> Escopo desta iniciativa: **núcleo DevTeam/system** (21 servers, 408 tools) — os SaaS de produto
> (connectors 362, crm 240, analytics 137, ml, communication, admin…) ficam **fora**.

## 1. Inventário vivo (gateway)
- **1562 tools / 38 servers** no total. **408 tools / 21 servers** no escopo DevTeam/system.
- Por server (escopo): services 32, deploy 30, session 29, product-owner 27, ai-governance 26,
  qa-engineer/product-manager/frontend 23, devops/config 22, backend 21, architecture 18,
  security 17, qa-mcp 15, infra 15, pipeline/docs 14, test-mcp 12, dev-twin 10, audit 9, devs-agent 6.
- O gateway expõe só `name/description/inputSchema` — os metadados `capability/required_scope/
  resource_type/data_domain` NÃO vêm na agregação (ficam internos ao PEP). Ver P4.

## 2. Reconciliação design × deployado
- Mapa = **278** tools. **133 existem** ao vivo; **145 NÃO existem** como tool MCP.
- **As 145 ausentes são o modelo "agente gera, tool guarda":** quem *gera* (`generate_*`,
  `analyze_*`, `define_*`, `map_*`, `review_*`) é o **LLM da persona**; a tool MCP só **persiste**
  (CRUD: `save_*/get_*/list_*/update_*/delete_*`). Ex.: não há `generate_react_component`; há
  `frontend-mcp.save_component`. **Isso é arquitetura, não bug.**

## 3. Decisão (2026-07-17): construir geradores determinísticos (híbrido)
Das 145, separar o que vira **tool MCP determinística** (template/regra, sem LLM — scaffolding
padronizado) do que **fica como agent-capability** (raciocínio aberto). Categorização:

### A) Geradores determinísticos — CONSTRUIR (~65) — alto valor como tool
- **IaC/DevOps**: generate_dockerfile, generate_docker_compose, generate_kubernetes_manifest,
  generate_terraform_module, generate_helm_chart, generate_github_actions_pipeline,
  generate_gitlab_ci_pipeline, generate_cloud_run_deploy, generate_gke_deploy, generate_iam_policy,
  generate_prometheus_rules, generate_grafana_dashboard, generate_secret_strategy, generate_runbook,
  generate_release_checklist, generate_observability_plan
- **Backend**: generate_fastapi_router, generate_service_layer, generate_repository_layer,
  generate_database_schema, generate_migration, generate_api_contract, generate_auth_policy,
  generate_event_contracts
- **Frontend**: generate_react_component, generate_nextjs_page, generate_custom_hook,
  generate_form_with_validation, generate_typescript_types, generate_storybook_story,
  generate_api_service, generate_component_variants, generate_wireframe (ASCII), create_design_tokens
- **Diagramas/ADR**: generate_c4_diagram, generate_sequence_diagram, generate_adr
- **QA**: generate_gherkin_scenarios, generate_unit_tests, generate_e2e_tests, generate_api_tests,
  generate_playwright_tests, generate_cypress_tests, generate_postman_collection,
  generate_k6_performance_test, generate_regression_suite, generate_smoke_test_suite,
  generate_uat_checklist, generate_quality_gate
- **PM/PO**: generate_epic, generate_feature_breakdown, generate_jira_tasks, generate_release_notes,
  generate_release_plan, generate_acceptance_criteria, generate_homologation_checklist,
  calculate_rice_score, generate_user_stories (template)
- **Security**: generate_security_controls, generate_api_security_spec, generate_compliance_report,
  generate_security_handbook
- **Handoffs**: generate_handoff_to_architecture / _design / _engineering

### B) Agent-only — NÃO construir (~70) — precisam de LLM
analyze_* (7), review_* (9), define_product_vision/_metrics/_mvp_scope/_bounded_contexts/
_system_modules/_integration_strategy/_non_functional_requirements/_definition_of_done/_ready,
map_* (8), evaluate_architecture_tradeoffs, optimize_query, suggest_refactor/_ui_components,
refine_feature, prioritize_backlog(_items), prepare_sprint_backlog, identify_scope_risks,
generate_go_to_market_brief/_discovery_questions/_ux_writing/_screen_brief/_feature_spec/
_component_spec/_technical_roadmap/_data_architecture/_observability_architecture/
_solution_blueprint/_threat_model/_threat_intelligence, split_design_and_frontend_tasks,
run_ui_feature_workflow, publish_security_requirements, document_component, classify_bug_severity.

### C) Validadores determinísticos — CONSTRUIR (~10)
validate_against_standards, validate_gdpr_compliance, validate_soc2_compliance,
validate_story_readiness, validate_story_testability, validate_design_system_usage,
validate_visual_accessibility, validate_contract, configure_alert, approve_service.

## 4. P2 — Consolidar sobreposições (32 colisões; reais abaixo)
| Domínio | Servers | Ação proposta |
|---------|---------|---------------|
| Credenciais (`*_credential`) | config-mcp + connectors-mcp | Dono = config-mcp (segredos da plataforma); connectors mantém só os de conector |
| Env/config (`read_env_file`, `set_env_var`, `audit_env_files`, `redact_env_secrets`, `list_environments`) | config-mcp + services-mcp | Dono = config-mcp; services-mcp delega/remove |
| Sugestões (`submit/get/list_suggestion(s)`) | ai-governance-mcp + session-mcp | Dono = session-mcp (ledger de sessão); ai-governance consome |
| QA planning (`get/list_test_plan(s)`) | qa-engineer-mcp + test-mcp | Dobrar test-mcp dentro de qa-engineer (já marcado) |
| Deploy/pipeline (`get/list_deployment(s)`, `get_pipeline`) | deploy-mcp/devops-mcp/pipeline-mcp | Fronteira: deploy=git/acr, pipeline=promoção, devops=scaffold IaC (remover CRUD duplicado) |
| Product vision (`*_product_vision`) | product-manager + product-owner | Dono = product-manager (visão); PO consome |
| `list_ml_algorithms` (analytics+scheduler), `provision_tenant` (analytics+notification), `list_templates` (docs+notification), `get_port_map` (ai-gov+services) | — | fora do escopo DevTeam (SaaS) ou dono óbvio |

Além disso, o **QA triplicado** do mapa: `qa-mcp` (runners: run_unit_tests/run_linter/run_type_check/
coverage) + `test-mcp` (planning CRUD) → **fachada única em qa-engineer** (wrapper), com os runners
de segurança (`run_security_scan`, `check_dependencies`) migrando p/ **security**.

## 5. P3 — Podar tools raras/mortas
Candidatas (confirmar uso real antes de remover): generate_postman_collection, analyze_complexity
(qa-mcp), register_token (dev-twin), list_repos (deploy), find_stale_docs / generate_doc_report /
get_audit_history (docs), search_governance_knowledge (ai-gov), cancel_queued_request (infra).
`request_vm` (infra) = Phase-2, marcar não-prod.

## 6. P4 — Qualidade
- **58/408** tools do escopo com **descrição < 40 chars** → reescrever (o gateway só mostra
  name+desc ao agente; descrição fraca = tool mal-usada).
- **24/408** sem input schema — auditar (muitos são list/health ok; alguns precisam de params).
- Expor `capability/required_scope/resource_type/data_domain` de forma consistente + `tool_matrix`
  caller→tool por persona (hoje read+write universal; deveria ser por capability do front-matter).

## 7. Sequência sugerida
1. **P1 ✅** (este doc + inventário vivo).
2. **P4-qualidade rápida** (baixo risco, alto ganho): reescrever as 58 descrições finas + auditar
   os 24 sem-params — melhora imediatamente o uso pelo agente.
3. **P2 consolidação** (piloto: QA triplicado → fachada qa-engineer; depois credenciais/env/sugestões).
4. **P4-geradores** (piloto: 1 persona determinística, ex. **devops** — dockerfile/terraform/k8s/helm —
   como template; validar no gateway; replicar às demais).
5. **P3 poda** (por último, após confirmar uso via telemetria/logs).
