# Deploy-MCP Skill: Clone & Sync Repositories

**Status**: ✅ Produção | **Versão**: 1.0.0 | **Data**: 2026-05-11

---

## 📋 Overview

Skill que garante que **todos os repositórios não-arquivados estejam clonados** em `~/repos` com a **branch `develop` atualizada localmente**.

### O Problema
```
Situação atual:
  ✅ 53/62 repos clonados (85%)
  ⚠️  9 repos faltando
  ⚠️  Apenas 6 com develop atualizado

Objetivo:
  ✅ 62/62 repos clonados (100%)
  ✅ Todos com develop sincronizado
  ✅ Automático e periódico
```

---

## 🎯 Funcionalidades

### 1️⃣ Clone Automático
- Clona apenas repos não-clonados
- Usa `--depth 5` para clone rápido (~5-10s por repo)
- Cria diretórios necessários
- Tratamento de erros robusto

### 2️⃣ Sincronização de Branch
- Detecta branch `develop`
- Faz checkout automático
- Fetch + Pull com `--ff-only` (sem merge)
- Relata conflitos se houver

### 3️⃣ Limpeza
- Remove branches remotas deletadas (`git remote prune`)
- Mantém repo limpo

### 4️⃣ Relatórios
- Status por repositório
- Percentuais de sincronização
- Últimos atualizados
- Problemas e falhas

---

## 🚀 Uso

### Status Rápido
```bash
./scripts/deploy-repo-clone status
```

### Clonar Tudo
```bash
./scripts/deploy-repo-clone clone
```

### Sincronizar Develop
```bash
./scripts/deploy-repo-clone sync
```

### Operação Completa
```bash
./scripts/deploy-repo-clone --all
```

### Python Direto
```bash
python3 db/clone_and_sync_repos.py --clone --sync --report
```

---

## 📊 Status Atual

### Contagem
```
Total de repos ativos:      62
Clonados localmente:        53/62 (85%)
Com branch develop:         6/62 (9%)
```

### Repos Faltando Clonar (9)
```
- allpfit
- condoconta
- dataforall-platform-api
- inknerd
- platform-crm
- platform-dataforall-frontend
- platform-dataforall-lib
- s3-connector
- sallve-dev
```

### Repos Sem Branch Develop (56)
Maioria dos repos:
```
- common-platform
- connectors-platform-deprecated
- data-plataform-v20
- database-manager
- dataforall-management
... (muitos mais)
```

---

## 🔧 Detalhes Técnicos

### Fluxo de Clone
```
1. Listar repos não-arquivados no PostgreSQL
2. Para cada repo:
   ├─ Verificar se já existe em ~/repos
   ├─ Se não existe:
   │  ├─ Fazer clone com --depth 5
   │  └─ Registrar resultado
   └─ Se existe: pular
3. Relatório de clones
```

### Fluxo de Sincronização
```
1. Para cada repo clonado:
   ├─ Verificar se tem branch develop remota
   ├─ Se não tem: pular com aviso
   ├─ Se tem:
   │  ├─ Checkout develop
   │  ├─ Fetch origin/develop
   │  ├─ Pull com --ff-only
   │  └─ Registrar status
   └─ Atualizar last_sync_at no banco
2. Relatório de sincronização
```

---

## 🔗 Integração CI/CD

### GitHub Actions (Daily)
```yaml
name: Clone and Sync Repos

on:
  schedule:
    - cron: '0 2 * * *'  # 2:00 AM UTC

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install psycopg2-binary
      
      - name: Clone and Sync
        env:
          POSTGRES_HOST: ${{ secrets.POSTGRES_HOST }}
          POSTGRES_USER: ${{ secrets.POSTGRES_USER }}
          POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
          PLATFORM_REPOS_DIR: /tmp/repos
        run: |
          python3 db/clone_and_sync_repos.py --all
      
      - name: Report Status
        run: |
          ls -1d /tmp/repos/*/.git | wc -l
```

### Cron Job (Local)
```bash
# Adicionar ao crontab (crontab -e)
# Clone & sync todos os dias às 2:00 AM
0 2 * * * cd /home/dev/repos/platform-devs && \
          source ~/.platform/env && \
          python3 db/clone_and_sync_repos.py --all >> ~/.platform/logs/repo-clone.log 2>&1
```

### Pre-push Hook (Validação)
```bash
#!/bin/bash
# .git/hooks/pre-push

echo "Validando sincronização de repositórios..."
python3 db/clone_and_sync_repos.py --report

if [ $? -ne 0 ]; then
  echo "⚠️  Falha na sincronização"
  exit 1
fi
```

---

## 🛠️ Scripts Inclusos

| Arquivo | Descrição |
|---------|-----------|
| `db/clone_and_sync_repos.py` | Script Python principal |
| `scripts/deploy-repo-clone` | CLI wrapper (bash) |
| `skills/repo-clone-sync.md` | Documentação skill |
| `DEPLOY_MCP_CLONE_SKILL.md` | Este guia |

---

## ⚙️ Configuração

### Variáveis de Ambiente
```bash
# Obrigatórias
POSTGRES_HOST=claude-dev
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres_password_local_dev
POSTGRES_DB=app

# Opcionais
PLATFORM_REPOS_DIR=~/repos  # Default
```

### Opções de Clone
```python
# Profundidade (atual: 5)
git clone --depth 5 <url> <path>

# Para clonar completo, editar script:
# Mudar: --depth 5
# Para: --depth 1000 ou remover --depth
```

---

## 📋 Próximas Ações

### Imediato (hoje)
- [ ] Executar `--all` para clonar + sincronizar
- [ ] Verificar logs para problemas
- [ ] Confirmar 62/62 clonados

### Curto Prazo (esta semana)
- [ ] Agendar cron job para sincronização diária
- [ ] Integrar com GitHub Actions
- [ ] Monitorar erros de conflito

### Médio Prazo (este mês)
- [ ] Adicionar suporte a branches customizadas
- [ ] Implementar clone paralelo (N workers)
- [ ] Dashboard de status em tempo real

---

## 🚨 Troubleshooting

### "Git command not found"
```bash
# Instalar git
sudo apt-get install git
# ou
brew install git
```

### "Permission denied" em clonagem
```bash
# Verificar SSH key
ssh -T git@github.com

# Se não funcionar, usar HTTPS
# Editar script: url para https://...
```

### "Branch develop not found"
```bash
# Alguns repos podem não ter develop
# Script reporta e pula automaticamente
# Ação: Criar branch develop se necessário

git -C ~/repos/<repo> checkout -b develop origin/develop
```

### "Conflitos ao fazer pull"
```bash
# Script usa --ff-only (sem merge)
# Se houver conflito, pula com aviso

# Manual: resolver conflito
cd ~/repos/<repo>
git pull origin develop --no-ff
git merge
git commit -m "..."
```

---

## 📞 Support

Para problemas ou melhorias:

1. Verificar logs:
   ```bash
   cat ~/.platform/logs/repo-clone.log
   ```

2. Executar validação:
   ```bash
   python3 db/clone_and_sync_repos.py --report
   ```

3. Contactar: caiog@dataforall.tech

---

## 📝 Log de Mudanças

### v1.0.0 (2026-05-11)
- ✨ Skill inicial criado
- 📥 Clone automático
- 🔄 Sincronização develop
- 📊 Relatórios
- 📚 Documentação

