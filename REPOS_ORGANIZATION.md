# 📊 Organização de Repositórios Locais

**Data**: 2026-05-10 | **Status**: Em progresso  
**Objetivo**: Consolidar 46 repositórios em uma estrutura coerente de branches, releases e CI/CD

---

## 📋 Inventário de Repositórios (46 total)

### Tier 1 — Core Platform (11)
| Repo | Branch | Remote | Status |
|------|--------|--------|--------|
| platform-devs | develop | platform-devs.git | ✅ In use (18 MCPs em dev) |
| platform-mcp | — | platform-mcp.git | — |
| platform-api-gateway | develop | platform-api-gateway.git | ✅ Active |
| platform-auth | develop | platform-auth.git | ✅ Active |
| platform-connectors | develop | platform-connectors.git | ✅ Active |
| platform-pipeline | main | platform-pipeline.git | — |
| platform-scheduler | main | platform-scheduler.git | — |
| platform-cloud | main | platform-cloud.git | ✅ Impl. MCP (8 tools) |
| platform-notification | — | — | — |
| platform-operation | — | — | — |
| platform-monitoring | — | — | — |

### Tier 2 — Shared Libraries (9)
| Repo | Branch | Purpose |
|------|--------|---------|
| platform-core-lib | main | Core abstractions |
| platform-auth-lib | main | Auth interfaces |
| platform-data-types-lib | main | Type definitions |
| platform-database-lib | main | DB abstractions |
| platform-events-lib | main | Event contracts |
| platform-files-lib | main | File handling |
| platform-log-lib | main | Logging |
| platform-observability-lib | main | Observability |
| platform-skills-lib | main | Skills framework |

### Tier 3 — Specialized Services (12)
| Repo | Branch | Purpose |
|------|--------|---------|
| platform-admin | main | Admin panel |
| platform-analytics | main | Analytics engine |
| platform-governance | main | Governance rules |
| platform-security | main | Security policies |
| platform-ml | main | ML pipelines |
| platform-notebook | main | Notebook service |
| platform-datalake | main | Data lake |
| platform-dataquality | main | Data quality |
| platform-iceberg | main | Iceberg tables |
| platform-agents-factory | main | Agents |
| platform-agents-lib | main | Agents lib |
| platform-dai | session/fase-4-5-6-final | DAI service (in dev) |

### Tier 4 — Legacy & Deprecated (6)
| Repo | Status |
|------|--------|
| finance-platform-* | 🗑️ Deprecated (3 repos) |
| connectors-platform-deprecated | 🗑️ Archived |
| run_clients-deprecated | 🗑️ Archived |
| data-plataform-v20 | 🗑️ Legacy |

### Tier 5 — External Partners (8)
| Repo | Purpose |
|------|---------|
| common-platform | Shared utilities |
| dataforall-platform-backend | Backend |
| dataforall-ui-connect | Frontend |
| dataforall-management | Management |
| platform-19 | — |
| database-manager | DB management |
| processor-platform | Processors |
| schedule-platform-deprecated | Archived |

---

## 🎯 Estratégia de Organização

### Branch Strategy (Git Flow)
```
main (production releases)
  └─ develop (integration branch)
      ├─ feature/cross-zilla-validators (Phase 2)
      ├─ feature/quality-gates-system (Phase 3)
      ├─ feature/zilla-observatory (Observability)
      └─ session/* (experimentation)
```

### Release Cadence
- **Weekly**: Library patches (Tier 2) → `main`
- **Bi-weekly**: Service releases (Tier 3) → `main` + tag
- **Monthly**: Platform releases (Tier 1) → `main` + GitHub Release

### CI/CD Gates
- ✅ Unit tests (80%+ coverage)
- ✅ Type checking (mypy/tsc)
- ✅ Linting (ruff/eslint)
- ✅ Security scan (bandit/npm audit)
- ✅ Dependency check (safety/npm-check)

---

## 🔄 Sincronização & Organização

### Passo 1 — Verificar Status Global
- [x] Listar todos os repos
- [x] Auditar branches por repo
- [ ] Verificar PRs abertos (deploy-mcp)
- [ ] Verificar mudanças não commitadas

### Passo 2 — Consolidar Branches
- [ ] `develop` ← `main` (atualizar em todos)
- [ ] Fechar PRs obsoletas
- [ ] Taguear releases pendentes

### Passo 3 — Atualizar CI/CD
- [ ] Criar `.github/workflows/ci.yml` global
- [ ] Configurar matrix de repos
- [ ] Habilitar quality gates

### Passo 4 — Documentação Centralizada
- [ ] REPOS_ROADMAP.md (fases de desenvolvimento)
- [ ] REPOS_DEPENDENCIES.md (dependency graph)
- [ ] REPOS_RELEASES.md (changelog unificado)

---

## 🚀 Deploy-MCP Tasks

### Priority 1 (Esta semana)
```bash
# Sincronizar branches principais
deploy-mcp::merge_branch(
  repos=["platform-devs", "platform-api-gateway", "platform-auth", "platform-connectors"],
  from="main",
  to="develop",
  strategy="squash"
)

# Criar PRs para Phase 2 features
deploy-mcp::create_pr(
  repo="platform-devs",
  title="feat: Phase 2 — Cross-Zilla Validators (18 tools)",
  base="main",
  head="feature/cross-zilla-validators"
)
```

### Priority 2 (Próximas 2 semanas)
```bash
# Taguear releases pendentes
deploy-mcp::tag_release(
  repos=[...],
  version="2.1.0",
  template="CHANGELOG_TEMPLATE.md"
)

# Gerar changelogs
deploy-mcp::generate_changelog(
  repo="platform-devs",
  from_tag="v2.0.0",
  to="HEAD"
)
```

---

## 📊 Métricas de Monitoramento

| Métrica | Target | Atual |
|---------|--------|-------|
| Repos sincronizados | 100% | 78% (36/46) |
| PRs em review | < 5 | — |
| CI/CD pass rate | > 95% | — |
| Code coverage | > 80% | — |
| Security issues | 0 critical | — |

---

## 🔗 Links & Referências

- GitHub Org: https://github.com/dataforalltech
- Deploy MCP Docs: `/home/dev/repos/platform-devs/deploy-mcp/`
- Session Tracking: `session-mcp` (lista de sessões ativas)

---

**Próximo review**: 2026-05-17 | **Owner**: caiog
