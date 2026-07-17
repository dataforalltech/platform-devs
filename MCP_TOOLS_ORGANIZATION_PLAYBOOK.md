# MCP Tools — Playbook de Organização & Melhoria (DevTeam/system)

**Status:** Fase 1 (Reconciliar) ✅ concluída. Fases P2–P4 abaixo com checklists acionáveis.
**Fontes:** `TOOLS_LIVE_INVENTORY.csv` (verdade viva, gateway) · `TOOLS_DEPENDENCY_MATRIX.csv` (design) · `MCP_TOOLS_RECONCILIATION.md` (análise).
**Escopo:** núcleo DevTeam/system — **21 servers, 408 tools** (SaaS de produto fora: connectors/crm/analytics/ml/communication/admin…).
**Decisões (2026-07-17):** (1) modelo "agente gera, tool guarda" mantido; (2) **construir geradores determinísticos** (template/regra) onde há valor de scaffolding; (3) escopo só DevTeam/system.

---

## 0. Como usar
Cada item é `- [ ]` marcável. "DoD por fase" no fim. Ordem recomendada: **P4a → P2 → P4b → P3**
(qualidade rápida → consolidação → geradores → poda). Cada mudança em server = editar tool + testes
(cov≥80) + `orm-lint`/ruff/mypy + build ACR + redeploy HML + **restart do platform-mcp** (registry lido no boot) + provar no `/mcp/tools/list`.

---

## 1. Estado atual (inventário)
- **Total gateway:** 1562 tools / 38 servers. **Escopo DevTeam:** 408 tools / 21 servers.
- Por server: services 32 · deploy 30 · session 29 · product-owner 27 · ai-governance 26 · qa-engineer/product-manager/frontend 23 · devops/config 22 · backend 21 · architecture 18 · security 17 · qa-mcp 15 · infra 15 · pipeline/docs 14 · test-mcp 12 · dev-twin 10 · audit 9 · devs-agent 6.
- Gateway expõe só `name/description/inputSchema` (metadados capability/scope ficam internos ao PEP).

## 2. Reconciliação (resumo)
- Mapa design = 278 → **133 vivas** + **145 "agente-gera"** (não existem como tool; o LLM gera, o CRUD persiste).
- **32 colisões** de nome entre servers (CRUD `*_artifact` e `check_health/status` são OK/namespaced; as reais estão na P2).
- Qualidade: **58** descrições < 40 chars · **24** sem input schema.

---

## P4a — QUALIDADE (rápido, baixo risco) — reescrever descrições + auditar schemas

### Checklist — 58 descrições fracas (<40 chars) → reescrever para 1 frase clara (verbo + objeto + efeito)
> Concentradas nos CRUD auto-gerados dos personas. Padrão sugerido: `"<Verbo> <entidade> <do escopo>; <retorno/efeito>."`

**architecture-mcp**
- [ ] `delete_artifact` (34ch) · [ ] `delete_c4_diagram` (39) · [ ] `get_artifact` (27) · [ ] `get_c4_diagram` (34) · [ ] `get_solution_blueprint` (39)

**backend-mcp**
- [ ] `get_artifact` (37) · [ ] `get_code_review` (37) · [ ] `get_database_schema` (34)

**devops-mcp**
- [ ] `delete_artifact` (38) · [ ] `delete_deployment` (36) · [ ] `delete_environment` (36) · [ ] `delete_pipeline` (35) · [ ] `get_artifact` (31) · [ ] `get_deployment` (29) · [ ] `get_environment` (29) · [ ] `get_pipeline` (28)

**frontend-mcp**
- [ ] `delete_artifact` (34) · [ ] `delete_component` (36) · [ ] `delete_form` (36) · [ ] `delete_page` (34) · [ ] `delete_story` (32) · [ ] `get_artifact` (27) · [ ] `get_component` (29) · [ ] `get_form` (29) · [ ] `get_page` (29) · [ ] `get_story` (25) · [ ] `update_story` (38)

**product-manager-mcp**
- [ ] `delete_artifact` (34) · [ ] `delete_feature_spec` (39) · [ ] `delete_gtm_brief` (35) · [ ] `delete_product_vision` (35) · [ ] `get_artifact` (27) · [ ] `get_feature_spec` (32) · [ ] `get_gtm_brief` (28) · [ ] `get_product_vision` (30) · [ ] `get_release_plan` (35)

**product-owner-mcp**
- [ ] `delete_product_vision` (35) · [ ] `delete_user_persona` (34) · [ ] `delete_user_story` (37) · [ ] `get_backlog_item` (34) · [ ] `get_mvp_scope` (38) · [ ] `get_po_artifact` (33) · [ ] `get_product_vision` (30) · [ ] `get_user_persona` (27) · [ ] `get_user_story` (30)

**qa-engineer-mcp**
- [ ] `delete_artifact` (34) · [ ] `delete_bug_report` (29) · [ ] `delete_test_case` (39) · [ ] `get_artifact` (27) · [ ] `get_bug_report` (22) · [ ] `get_quality_gate` (37) · [ ] `get_test_case` (32) · [ ] `get_test_plan` (33)

**security-mcp / services-mcp / audit-mcp / config-mcp**
- [ ] `security-mcp.get_cvss_assessment` (34) · [ ] `security-mcp.get_threat_model` (36) · [ ] `services-mcp.unregister_service` (30) · [ ] `audit-mcp.list_audits` (38) · [ ] `config-mcp.delete_credential` (39)

### Checklist — 24 tools sem input schema (auditar: precisa de param? ou é list/health legítimo)
- [ ] `ai-governance-mcp.get_port_map` · [ ] `ai-governance-mcp.status` · [ ] `config-mcp.get_physical_info` · [ ] `config-mcp.get_session_tenant_config` · [ ] `config-mcp.list_environments` · [ ] `config-mcp.list_tenants`
- [ ] (+18 restantes — extrair de `TOOLS_LIVE_INVENTORY.csv` col `n_params==0`: dev-twin/session/services/pipeline/docs/audit health & list)

### DoD P4a
- [ ] Toda tool do escopo com descrição ≥ 1 frase acionável; nenhuma < 40ch.
- [ ] Cada `n_params==0` justificado (list/health) ou recebe filtros.
- [ ] Redeploy dos servers tocados + `/mcp/tools/list` reflete as novas descrições.

---

## P2 — CONSOLIDAÇÃO (estrutural)

### 2.1 QA triplicado → fachada única em qa-engineer  *(piloto de consolidação)*
- [ ] Mapear tools de `qa-mcp` (runners: run_unit_tests/run_e2e_tests/run_linter/run_type_check/run_api_tests/get_coverage_report/check_accessibility/visual_regression/screenshot_page/generate_qa_report) e `test-mcp` (planning CRUD: create_test_plan/add_scenario/generate_scenarios/record_result/run_checklist/…).
- [ ] Decidir modelo: qa-engineer expõe fachada; qa-mcp/test-mcp viram backend interno (S2S) OU tools deprecadas com redirect.
- [ ] Mover `run_security_scan` + `check_dependencies` (qa-mcp) → **security-mcp**.
- [ ] `check_doc_standards` (qa-mcp ∩ docs-mcp) → manter em docs-mcp; qa-mcp remove.
- [ ] Atualizar callers (tool_matrix) + `MCP_TOOLS_REFERENCE.md`.
- [ ] Redeploy + provar no gateway; testes verdes.

### 2.2 Credenciais — dono = config-mcp
- [ ] `get/set/list/delete_credential` duplicados em `connectors-mcp`: manter em config-mcp (segredos de plataforma); connectors mantém só credenciais **de conector** (renomear p/ evitar colisão) ou consumir config-mcp via S2S.

### 2.3 Env/config — dono = config-mcp
- [ ] `read_env_file`, `set_env_var`, `audit_env_files`, `redact_env_secrets`, `list_environments` duplicados em `services-mcp` → services delega a config-mcp ou remove.

### 2.4 Sugestões — dono = session-mcp
- [ ] `submit/get/list_suggestion(s)` em `ai-governance-mcp` ∩ `session-mcp` → session-mcp é o ledger; ai-governance consome via S2S.

### 2.5 Product vision — dono = product-manager
- [ ] `get/set/list/delete_product_vision` em PM ∩ PO → PM é dono da visão; PO consome (remover CRUD duplicado no PO).

### 2.6 Deploy/pipeline/devops — fronteiras
- [ ] `get/list_deployment(s)` (deploy-mcp ∩ devops-mcp) e `get_pipeline` (devops ∩ pipeline): deploy=git/ACR, pipeline=promoção/gates, devops=scaffold IaC. Remover CRUD de deployment/pipeline duplicado no devops-mcp.

### DoD P2
- [ ] 0 colisões "reais" (fora CRUD `*_artifact` namespaced e health/status).
- [ ] Cada domínio com **1 dono**; duplicados removidos/redirecionados; callers atualizados; verdes no gateway.

---

## P4b — GERADORES DETERMINÍSTICOS (construir ~65 + ~10 validadores)
> Template/regra, **sem LLM**. `input_json` = spec estruturada → artefato + persistência (save_*). Piloto: **devops**.

### devops-mcp (16)  *(piloto)*
- [ ] generate_dockerfile · [ ] generate_docker_compose · [ ] generate_kubernetes_manifest · [ ] generate_terraform_module · [ ] generate_helm_chart · [ ] generate_github_actions_pipeline · [ ] generate_gitlab_ci_pipeline · [ ] generate_cloud_run_deploy · [ ] generate_gke_deploy · [ ] generate_iam_policy · [ ] generate_prometheus_rules · [ ] generate_grafana_dashboard · [ ] generate_secret_strategy · [ ] generate_runbook · [ ] generate_release_checklist · [ ] generate_observability_plan

### backend-mcp (8)
- [ ] generate_fastapi_router · [ ] generate_service_layer · [ ] generate_repository_layer · [ ] generate_database_schema · [ ] generate_migration · [ ] generate_api_contract · [ ] generate_auth_policy · [ ] generate_event_contracts

### frontend-mcp (10)
- [ ] generate_react_component · [ ] generate_nextjs_page · [ ] generate_custom_hook · [ ] generate_form_with_validation · [ ] generate_typescript_types · [ ] generate_storybook_story · [ ] generate_api_service · [ ] generate_component_variants · [ ] generate_wireframe (ASCII) · [ ] create_design_tokens

### qa-engineer-mcp (11)  *(pular postman → ver P3)*
- [ ] generate_gherkin_scenarios · [ ] generate_unit_tests · [ ] generate_e2e_tests · [ ] generate_api_tests · [ ] generate_playwright_tests · [ ] generate_cypress_tests · [ ] generate_k6_performance_test · [ ] generate_regression_suite · [ ] generate_smoke_test_suite · [ ] generate_uat_checklist · [ ] generate_quality_gate

### architecture-mcp (3)
- [ ] generate_c4_diagram · [ ] generate_sequence_diagram · [ ] generate_adr

### product-manager / product-owner (9)
- [ ] pm: generate_release_plan · [ ] pm: generate_acceptance_criteria · [ ] pm: calculate_rice_score · [ ] pm: generate_handoff_to_architecture/_design/_engineering
- [ ] po: generate_epic · [ ] po: generate_feature_breakdown · [ ] po: generate_jira_tasks · [ ] po: generate_release_notes · [ ] po: generate_user_stories (template) · [ ] po: generate_homologation_checklist

### security-mcp (4)
- [ ] generate_security_controls · [ ] generate_api_security_spec · [ ] generate_compliance_report · [ ] generate_security_handbook

### Validadores determinísticos (~10)
- [ ] validate_against_standards · [ ] validate_gdpr_compliance · [ ] validate_soc2_compliance · [ ] validate_story_readiness · [ ] validate_story_testability · [ ] validate_design_system_usage · [ ] validate_visual_accessibility · [ ] validate_contract · [ ] configure_alert · [ ] approve_service

### FICAM agent-only (NÃO construir, ~70)
analyze_* (7) · review_* (9) · define_product_vision/_metrics/_mvp_scope/_bounded_contexts/_system_modules/_integration_strategy/_non_functional_requirements/_definition_of_done/_ready · map_* (8) · evaluate_architecture_tradeoffs · optimize_query · suggest_refactor/_ui_components · refine_feature · prioritize_backlog(_items) · prepare_sprint_backlog · identify_scope_risks · generate_go_to_market_brief/_discovery_questions/_ux_writing/_screen_brief/_feature_spec/_component_spec/_technical_roadmap/_data_architecture/_observability_architecture/_solution_blueprint/_threat_model/_threat_intelligence · split_design_and_frontend_tasks · run_ui_feature_workflow · publish_security_requirements · document_component · classify_bug_severity.

### DoD P4b (por persona)
- [ ] Cada gerador: input schema estruturado + saída determinística + persiste via save_* + teste (fixture→artefato) cov≥80 + metadados (capability/required_scope=`<domain>:<res>:write`/resource_type/data_domain).
- [ ] Provado no gateway (tool aparece + executa E2E via agente).

---

## P3 — PODA (por último, após confirmar uso real)
- [ ] `analyze_complexity` (qa-mcp) — deprecar (raro)
- [ ] `register_token` (dev-twin) — raro; validar
- [ ] `list_repos` (deploy) — raro
- [ ] `find_stale_docs` / `generate_doc_report` / `get_audit_history` (docs) — raros
- [ ] `search_governance_knowledge` (ai-gov) — raro
- [ ] `cancel_queued_request` (infra) — raro
- [ ] `generate_postman_collection` (qa) — raro → **não** construir na P4b
- [ ] `request_vm` (infra) — marcar Phase-2 / não-prod
- [ ] Confirmar uso via telemetria/logs do gateway antes de remover; deprecar (aviso) → remover no ciclo seguinte.

### DoD P3
- [ ] Nenhuma tool removida sem evidência de não-uso; deprecações anunciadas; `MCP_TOOLS_REFERENCE.md` atualizado.

---

## Sequência / milestones
1. **P4a** (qualidade) — 1 passada em todos os servers do escopo tocados.
2. **P2.1** (QA triplicado — piloto de consolidação) → 2.2–2.6.
3. **P4b** (geradores — piloto devops → replica).
4. **P3** (poda).
- A cada fase: build→ACR→redeploy HML→**restart platform-mcp**→provar `/mcp/tools/list`→atualizar `TOOLS_LIVE_INVENTORY.csv` + este checklist.
