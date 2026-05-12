# Skill: Repository Sync & Validate (Deploy-MCP)

Sincroniza e valida repositórios em 3 fontes: Filesystem, PostgreSQL, GitHub

## Features

✅ **Validação Completa**
- Compara repos em filesystem (~repos), banco de dados e GitHub
- Identifica discrepâncias e conflitos
- Gera relatório detalhado

✅ **Sincronização Bidirecional**
- Repo local → banco de dados
- GitHub → banco de dados
- Reconciliação automática

✅ **Relatórios**
- Estatísticas por fonte
- Listagem de problemas
- JSON para integração com CI/CD

## Usage

### Validação (apenas leitura)
```bash
python3 db/validate_and_sync_repos.py --validate
```

### Reconciliação (corrige problemas)
```bash
python3 db/validate_and_sync_repos.py --reconcile
```

### Relatório detalhado
```bash
python3 db/validate_and_sync_repos.py --report
```

### Tudo (validar + reconciliar + relatório)
```bash
python3 db/validate_and_sync_repos.py --all
```

## Integração CI/CD

### GitHub Actions
```yaml
- name: Validate Repository Sync
  run: |
    python3 db/validate_and_sync_repos.py --validate --report
    if [ $? -ne 0 ]; then exit 1; fi
```

### Cron Job (diário)
```bash
0 3 * * * cd /home/dev/repos/platform-devs && python3 db/validate_and_sync_repos.py --all
```

### Pre-commit Hook
```bash
#!/bin/bash
python3 db/validate_and_sync_repos.py --validate
```

## Status Atual (2026-05-11)

| Fonte | Count | Status |
|-------|-------|--------|
| Filesystem | 54 | ⚠️ Faltam 56 repos |
| PostgreSQL | 110 | ✅ Sincronizado |
| GitHub | 107 | ⚠️ 3 deletados? |

### Ações Recomendadas

1. **Sincronizar repos do GitHub localmente**
   ```bash
   python3 db/validate_and_sync_repos.py --reconcile
   ```

2. **Verificar 3 repos deletados no GitHub**
   - dataforall-ui-connect
   - finance-platform-frontend
   - finance-platform-new_product-

3. **Agendar sincronização periódica**
   ```bash
   # Adicionar ao crontab
   0 3 * * * cd /home/dev/repos/platform-devs && python3 db/validate_and_sync_repos.py --all
   ```

## Output Format

```json
{
  "validation": {
    "local_count": 54,
    "db_count": 110,
    "github_count": 107,
    "issue_count": 59
  },
  "issues": [
    {"type": "missing_local", "repo": "acordo-online"},
    {"type": "missing_github", "repo": "dataforall-ui-connect"}
  ],
  "reconciled": 10,
  "failed": 0
}
```

## Troubleshooting

### "GitHub CLI not authenticated"
```bash
gh auth login
```

### "PostgreSQL connection error"
Check `~/.platform/env`:
```bash
source ~/.platform/env
echo $POSTGRES_HOST
```

### Discrepâncias persistem
1. Verificar URLs dos repos
2. Confirmar permissões no GitHub
3. Checar integridade do banco

## Related

- `sync_github_to_postgres.py` - Sincronização GitHub → PostgreSQL
- `sync_branches_v2.py` - Sincronização de branches
- Deploy-MCP service
