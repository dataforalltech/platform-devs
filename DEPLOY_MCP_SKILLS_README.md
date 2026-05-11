# Deploy-MCP Skills - Guia Rápido

Dois skills completos para gerenciamento de repositórios no Deploy-MCP.

---

## 🎯 Uso Rápido

### Skill 1: Validar Sincronização
```bash
./scripts/deploy-repo-sync --all
```
✅ Validar, reconciliar e gerar relatório

---

### Skill 2: Clonar e Sincronizar [NOVO]
```bash
./scripts/deploy-repo-clone --all
```
✅ Clonar repos faltantes + sincronizar develop + relatório

---

## 📋 Detalhes

### Skill 1: Repository Sync & Validate
**Arquivo**: `DEPLOY_MCP_SYNC_SKILL.md`

Valida sincronização em 3 fontes:
- 🖥️ Filesystem (~repos)
- 💾 PostgreSQL (banco)
- 🐙 GitHub (remoto)

```bash
./scripts/deploy-repo-sync validate       # Validar
./scripts/deploy-repo-sync reconcile      # Corrigir
./scripts/deploy-repo-sync --all          # Tudo
```

---

### Skill 2: Clone & Sync Repositories
**Arquivo**: `DEPLOY_MCP_CLONE_SKILL.md`

Garante todos os repos em ~/repos com develop atualizado:

```bash
./scripts/deploy-repo-clone clone         # Clonar faltantes
./scripts/deploy-repo-clone sync          # Sincronizar develop
./scripts/deploy-repo-clone --all         # Tudo
```

---

## 🚀 Executar Agora

### 1. Validar Sincronização
```bash
python3 db/validate_and_sync_repos.py --validate
```

### 2. Clonar e Sincronizar
```bash
python3 db/clone_and_sync_repos.py --all
```

### 3. Verificar Status
```bash
./scripts/deploy-repo-clone status
```

---

## 🔧 Agendar (Cron)

```bash
# Adicionar ao crontab (crontab -e)

# Validação diária às 3:00 AM
0 3 * * * cd /home/dev/repos/platform-devs && \
          source ~/.platform/env && \
          python3 db/validate_and_sync_repos.py --all

# Clone & Sync diário às 2:00 AM
0 2 * * * cd /home/dev/repos/platform-devs && \
          source ~/.platform/env && \
          python3 db/clone_and_sync_repos.py --all
```

---

## 📊 Status Atual

```
📦 Validação:
   Filesystem:    54 repos
   PostgreSQL:   110 repos
   GitHub:       107 repos
   Discrepâncias: 59

📥 Clone & Sync:
   Repos ativos:         62
   Clonados:            53/62 (85%)
   Com develop:          6/62 (9%)
   Faltando clonar:      9 repos
```

---

## 🔗 GitHub Actions

Exemplos em:
- `DEPLOY_MCP_SYNC_SKILL.md` (seção CI/CD)
- `DEPLOY_MCP_CLONE_SKILL.md` (seção CI/CD)

---

## 📚 Documentação Completa

1. `DEPLOY_MCP_SYNC_SKILL.md` - Skill de Validação
2. `DEPLOY_MCP_CLONE_SKILL.md` - Skill de Clone & Sync

---

## ✨ Resumo

✅ Dois skills prontos para produção
✅ CLI wrappers para fácil uso
✅ Documentação completa
✅ Integração CI/CD
✅ Scheduled execution support
