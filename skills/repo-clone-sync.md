# Skill: Clone & Sync Repositories (Deploy-MCP)

Garante que todos os repositórios não-arquivados estejam clonados em ~/repos com a branch `develop` atualizada.

## Features

✅ **Clone Automático**
- Clone apenas repos não-clonados
- Usa `--depth 5` para clone rápido
- Tratamento robusto de erros

✅ **Sincronização**
- Checkout branch develop
- Fetch + Pull com ff-only
- Detecta conflitos

✅ **Limpeza**
- Prune de branches remotas deletadas
- Mantém repositório limpo

✅ **Relatórios**
- Status por repositório
- Percentuais de clonagem/sincronização
- Últimos atualizados

## Usage

### Clone Repos Não-Clonados
```bash
python3 db/clone_and_sync_repos.py --clone
# ou
./scripts/deploy-repo-clone clone
```

### Sincronizar Branch Develop
```bash
./scripts/deploy-repo-clone sync
```

### Status Completo (Clone + Sync + Report)
```bash
./scripts/deploy-repo-clone status
```

### Tudo Junto (Clone + Sync + Prune + Report)
```bash
./scripts/deploy-repo-clone --all
```

## Current Status

```
📦 Total de repos ativos: 62
✅ Clonados localmente: 53/62 (85%)
🌿 Com branch develop: 6/62 (9%)

❌ Faltando clonar: 9 repos
⚠️  Sem branch develop: 56 repos
```

## Próximos Passos

1. Clonar 9 repos faltantes
2. Sincronizar develop em todos os repos
3. Agendar sincronização periódica

## Integration with CI/CD

### GitHub Actions
```yaml
- name: Clone and Sync Repositories
  run: |
    python3 db/clone_and_sync_repos.py --all
    git status
```

### Cron Job (diário)
```bash
0 2 * * * cd /home/dev/repos/platform-devs && \
          source ~/.platform/env && \
          python3 db/clone_and_sync_repos.py --all
```

## Related Skills

- `repo-sync-validate` - Validação de sincronização
- Deploy-MCP service
