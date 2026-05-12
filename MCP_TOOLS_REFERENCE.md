# MCP Tools Reference — Complete List

**Data**: 2026-05-11  
**Repositório**: platform-devs  
**Total de MCPs**: 32 (17 Python + 8 Zillas + 6 Service MCPs + 1 Test)

---

## 🐍 Python MCPs (17)

### 1. ADMIN-MCP
Gerenciamento de usuários, roles, tenants e domínios
- `list_users` — Listar usuários
- `create_user` — Criar novo usuário
- `delete_user` — Deletar usuário
- `update_user` — Atualizar dados de usuário
- `assign_role` — Atribuir role a usuário
- `reset_password` — Resetar senha de usuário
- `update_tenant` — Atualizar configurações de tenant
- `manage_domains` — Gerenciar domínios
- `manage_permissions` — Gerenciar permissões
- `manage_quotas` — Gerenciar quotas

### 2. AGENT-TWIN-MCP
Autenticação e contexto de sessão
- `authenticate` — Validar token e inicializar sessão
- `whoami` — Retornar info do usuário autenticado
- `get_twin_context` — Contexto completo (usuário + ambiente)
- `context_status` — Métricas de contexto e recomendação
- `refresh_context` — Re-coletar contexto do ambiente

### 3. AI-GOVERNANCE-MCP
Políticas de IA e governança
- `check_ai_policies` — Validar conformidade com políticas de IA
- `detect_scope_drift` — Detectar desvios de escopo
- `suggest_improvements` — Sugerir melhorias
- `validate_usage` — Validar uso conforme políticas
- `analyze_compliance` — Analisar conformidade
- `monitor_ai_safety` — Monitorar segurança de IA
- `generate_policy_report` — Gerar relatório de políticas
- `validate_model_behavior` — Validar comportamento de modelo
- `check_bias` — Verificar bias

### 4. AUDIT-MCP
Trilha de auditoria e conformidade
- `log_action` — Registrar ação na trilha de auditoria
- `list_audit_logs` — Listar logs de auditoria
- `check_compliance` — Verificar conformidade
- `generate_report` — Gerar relatório de auditoria
- `verify_decision` — Verificar decisão registrada
- `export_logs` — Exportar logs
- `archive_logs` — Arquivar logs antigos
- `filter_logs` — Filtrar logs
- `search_logs` — Buscar logs
- `analyze_patterns` — Analisar padrões em logs

### 5. AUTH-MCP
Autenticação e autorização
- `validate_token` — Validar token de acesso
- `create_jwt` — Criar JWT
- `check_session` — Verificar status de sessão
- `revoke_token` — Revogar token
- `list_active_sessions` — Listar sessões ativas
- `refresh_token` — Refrescar token expirado
- `create_api_key` — Criar chave de API
- `revoke_api_key` — Revogar chave de API
- `verify_permissions` — Verificar permissões de usuário
- `get_user_roles` — Obter roles do usuário

### 6. CACHE-MCP
Gerenciamento de cache
- `set_cache` — Armazenar valor em cache
- `get_cache` — Recuperar valor de cache
- `invalidate_cache` — Invalidar entrada de cache
- `clear_cache` — Limpar todo o cache
- `check_stats` — Verificar estatísticas de cache
- `configure_cache` — Configurar parâmetros de cache
- `view_cache_contents` — Visualizar conteúdo do cache
- `export_cache` — Exportar cache
- `import_cache` — Importar cache
- `analyze_cache_performance` — Analisar performance de cache

### 7. CONFIG-MCP
Gerenciamento de configuração e secrets
- `get_config` — Obter configuração
- `set_config` — Definir configuração
- `get_secret` — Obter secret
- `set_secret` — Definir secret
- `delete_secret` — Deletar secret
- `list_secrets` — Listar todos os secrets
- `validate_config` — Validar formato de configuração
- `rotate_secrets` — Rotacionar secrets
- `export_config` — Exportar configuração
- `import_config` — Importar configuração

### 8. CONNECTORS-MCP
Gerenciamento de conectores e integrações
- `list_connectors` — Listar conectores disponíveis
- `create_connector` — Criar novo conector
- `delete_connector` — Deletar conector
- `enable_connector` — Habilitar conector
- `disable_connector` — Desabilitar conector
- `test_connection` — Testar conexão
- `update_credentials` — Atualizar credenciais
- `validate_credentials` — Validar credenciais
- `list_integrations` — Listar integrações
- `sync_data` — Sincronizar dados

### 9. DEPLOY-MCP
Operações de deploy e CI/CD
- `create_commit` — Criar commit no Git
- `create_pr` — Criar pull request
- `merge_branch` — Fazer merge de branch
- `create_deployment` — Criar deployment
- `trigger_workflow` — Disparar workflow de CI/CD
- `create_release` — Criar release
- `tag_release` — Taguear release
- `push_to_registry` — Push para registry (Docker)
- `push_acr` — Push para Azure Container Registry
- `generate_changelog` — Gerar changelog

### 10. DOCS-MCP
Gerenciamento de documentação
- `generate_doc` — Gerar documentação
- `audit_docs` — Auditar documentação
- `validate_template` — Validar template de doc
- `lint_markdown` — Validar sintaxe Markdown
- `publish_docs` — Publicar documentação
- `generate_api_docs` — Gerar documentação de API
- `generate_architecture_docs` — Gerar docs de arquitetura
- `generate_user_guide` — Gerar guia do usuário
- `validate_links` — Validar links em docs
- `build_docs` — Compilar documentação

### 11. GOVERNANCE-MCP
Governança de dados e acesso
- `list_policies` — Listar políticas
- `create_policy` — Criar nova política
- `update_policy` — Atualizar política
- `delete_policy` — Deletar política
- `check_permission` — Verificar permissão específica
- `enforce_rls` — Enforcar Row Level Security
- `audit_access` — Auditar acessos
- `analyze_permissions` — Analisar permissões
- `validate_governance` — Validar conformidade de governança
- `generate_access_report` — Gerar relatório de acesso

### 12. INFRA-MCP
Infraestrutura como código
- `create_infrastructure` — Criar infraestrutura
- `update_infrastructure` — Atualizar infraestrutura
- `destroy_infrastructure` — Deletar infraestrutura
- `plan_terraform` — Planejar mudanças Terraform
- `apply_policy` — Aplicar política de infraestrutura
- `validate_infrastructure` — Validar configuração
- `generate_adr` — Gerar Architecture Decision Record
- `scan_compliance` — Escanear conformidade
- `rollback_infrastructure` — Fazer rollback de mudanças
- `export_infrastructure` — Exportar configuração

### 13. PIPELINE-MCP
Gerenciamento de pipelines de CI/CD
- `trigger_pipeline` — Disparar pipeline
- `check_status` — Verificar status de pipeline
- `list_gates` — Listar quality gates
- `promote_build` — Promover build entre ambientes
- `skip_gate` — Pular quality gate
- `retry_stage` — Reexecutar estágio
- `view_logs` — Visualizar logs de pipeline
- `get_artifacts` — Obter artefatos
- `cancel_pipeline` — Cancelar pipeline em execução
- `rollback` — Fazer rollback de deployment

### 14. QA-MCP
Testes e qualidade de código
- `run_tests` — Executar testes
- `check_coverage` — Verificar cobertura de testes
- `lint_code` — Verificar estilo de código
- `scan_security` — Escanear vulnerabilidades
- `validate_code_quality` — Validar qualidade
- `run_performance_tests` — Executar testes de performance
- `analyze_test_results` — Analisar resultados
- `generate_coverage_report` — Gerar relatório de cobertura
- `generate_report` — Gerar relatório de testes
- `check_accessibility` — Verificar acessibilidade

### 15. SCHEDULER-MCP
Agendamento de tarefas
- `create_task` — Criar tarefa agendada
- `schedule_job` — Agendar job
- `list_scheduled` — Listar tarefas agendadas
- `get_task_status` — Obter status de tarefa
- `cancel_task` — Cancelar tarefa
- `pause_task` — Pausar tarefa
- `resume_task` — Resumir tarefa
- `retry_task` — Reexecutar tarefa
- `update_schedule` — Atualizar agendamento
- `check_history` — Verificar histórico de execução

### 16. SERVICES-MCP
Registro e gerenciamento de serviços
- `register_service` — Registrar novo serviço
- `deregister_service` — Remover serviço
- `list_services` — Listar serviços registrados
- `check_health` — Verificar saúde de serviço
- `get_port` — Obter porta de serviço
- `configure_service` — Configurar serviço
- `update_service` — Atualizar configuração
- `restart_service` — Reiniciar serviço
- `get_service_metrics` — Obter métricas
- `monitor_service` — Monitorar serviço

### 17. SESSION-MCP
Gerenciamento de sessões
- `start_session` — Iniciar nova sessão
- `end_session` — Finalizar sessão
- `resume_session` — Retomar sessão anterior
- `list_sessions` — Listar sessões ativas
- `get_session` — Obter dados de sessão
- `update_session` — Atualizar sessão
- `save_checkpoint` — Salvar checkpoint
- `archive_session` — Arquivar sessão
- `restore_session` — Restaurar sessão arquivada
- `cleanup_sessions` — Limpar sessões antigas

---

## 🔧 Node MCPs - Zillas (8)

Zillas são MCPs especializados compilados em Node.js para domínios específicos:

### 1. ARCHZILLA-MCP
Arquitetura de sistemas
- Análise de requisitos arquiteturais
- Recomendações de estilos e padrões
- Geração de diagramas C4
- Definição de bounded contexts
- Avaliação de trade-offs arquiteturais

### 2. BACKZILLA-MCP
Backend e APIs
- Geração de APIs (FastAPI, NestJS)
- Design de schemas de banco de dados
- Geração de repositories e services
- Testes backend (unit, integration)
- Review de segurança

### 3. FRONTZILLA-PIXELFERA-MCP
Frontend e UI
- Geração de componentes React
- Design tokens e temas
- Validação de acessibilidade
- Testes frontend (unit, E2E)
- Review de consistência UI

### 4. OPSZILLA-MCP
Operações e DevOps
- Geração de Dockerfiles
- Configuração de Kubernetes
- Setup de CI/CD (GitHub Actions, GitLab CI)
- Monitoramento (Grafana, Prometheus)
- Gerenciamento de secrets

### 5. POZILLA-MCP
Gestão de Produto
- Análise de requisitos de negócio
- Geração de user stories
- Criação de roadmaps
- Prioritização de backlog
- Definição de critérios de aceitação

### 6. PRODUCTZILLA-MCP
Estratégia de Produto
- Pesquisa de mercado
- Análise de personas
- Mapeamento de jornadas
- Go-to-market strategy
- Métricas e KPIs

### 7. QAZILLA-MCP
QA e Testes
- Geração de casos de testes
- Testes E2E (Playwright, Cypress)
- Smoke tests e regression tests
- UAT checklists
- Performance testing (k6)

### 8. SECZILLA-MCP
Segurança
- Modelo de ameaças (STRIDE)
- Mapeamento de superfície de ataque
- Controles de segurança
- Remediação de vulnerabilidades
- Conformidade (LGPD, GDPR)

---

## 📊 Resumo de Cobertura

| Categoria | MCPs | Total de Tools |
|-----------|------|----------------|
| Identity & Session | 4 | ~40 |
| Infrastructure | 3 | ~30 |
| Quality & Deploy | 3 | ~30 |
| Documentation | 2 | ~20 |
| Services | 6 | ~60 |
| **Zillas** | 8 | ~200+ |
| **TOTAL** | 32 | **~400+ tools** |

---

## 🎯 Uso Recomendado

### Para Desenvolvimento
- **Backend**: BackZilla, ArchZilla, QAZilla, SecZilla
- **Frontend**: FrontZilla, ArchZilla, QAZilla
- **DevOps**: OpsZilla, ArchZilla, Pipeline-MCP

### Para Operações
- **Deploy**: Deploy-MCP, Pipeline-MCP, OpsZilla
- **Monitoramento**: Services-MCP, OpsZilla
- **Segurança**: SecZilla, Governance-MCP, Audit-MCP

### Para Gestão
- **Roadmap**: POZilla, ProductZilla, Session-MCP
- **Governança**: Governance-MCP, AI-Governance-MCP, Admin-MCP
- **Configuração**: Config-MCP, Connectors-MCP

---

**Última Atualização**: 2026-05-11  
**Status**: ✅ Todos os MCPs funcionais
