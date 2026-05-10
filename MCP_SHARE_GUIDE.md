# Compartilhando MCPs HTTP com o Time

**Status:** ✅ Production Ready | **Data:** 2026-05-10

## 📋 Visão Geral

Os MCPs estão **centralizados em HTTP** na VM `claude-dev`:

```
┌─────────────────────────────────────┐
│      Claude-dev VM (EC2)            │
│   ─────────────────────────────     │
│   Docker Network                    │
│   ├─ 18 System MCPs (7100-7116)     │
│   ├─ 8 Zilla MCPs (7118-7125)       │
│   └─ Registry (8000)                │
└─────────────────────────────────────┘
         ↑ (HTTP)
    N Users / N Projects
```

**Benefícios:**
- ✅ Configuração centralizada
- ✅ Sempre atualizado (uma única fonte)
- ✅ Múltiplos usuários simultâneos
- ✅ Múltiplos projetos
- ✅ Funciona em qualquer OS (Windows, Mac, Linux)

---

## 🚀 Setup para Cada Usuário

### Opção 1: Usar o Wrapper HTTP (Recomendado)

**Para cada usuário/máquina:**

```bash
# 1. Clonar repo
git clone https://github.com/seu-org/platform-devs.git
cd platform-devs

# 2. Copiar wrapper para máquina local
cp mcp-http-wrapper.py ~/mcp-wrapper/

# 3. Adicionar ao Claude Code (~/.claude/settings.json)
{
  "mcpServers": {
    "mcp-http-wrapper": {
      "command": "python3",
      "args": ["/home/seu-usuario/mcp-wrapper/mcp-http-wrapper.py"],
      "disabled": false,
      "alwaysAllow": ["mcp__mcp_http_wrapper__*"]
    }
  }
}

# 4. Reiniciar Claude Code
```

**Pronto!** Usuário tem acesso a 170+ ferramentas.

### Opção 2: Usar .mcp-http.json (Documentação)

```bash
# Referência das portas e endpoints
cat .mcp-http.json
```

---

## 📦 Arquivos de Distribuição

No repositório `platform-devs/`:

```
platform-devs/
├── .mcp-http.json                    ← Config compartilhada
├── mcp-http-wrapper.py               ← Wrapper HTTP
├── install-mcp-wrapper.py            ← Setup automático (Python)
├── install-mcp-wrapper.bat           ← Setup automático (Windows)
├── INSTALL_WINDOWS_README.md         ← Guia Windows
├── MCP_WRAPPER_SETUP.md              ← Guia completo
├── MCP_SHARE_GUIDE.md                ← Este arquivo
└── docker-compose-system.yml         ← Infraestrutura (Admin)
```

---

## 👥 Para Diferentes Públicos

### 1️⃣ **Desenvolvedores** (usam os MCPs)

Apenas executar:
```bash
python install-mcp-wrapper.py
# ou
./install-mcp-wrapper.bat  # Windows
```

Depois configure em Claude Code → Settings → MCP Servers.

### 2️⃣ **DevOps / Infraestrutura** (mantém os MCPs)

Responsável por:
```bash
# Na VM claude-dev
docker compose -f docker-compose-system.yml up -d
docker compose logs -f

# Monitorar saúde
curl http://localhost:8000/services
```

### 3️⃣ **Arquitetura / Liderança Técnica**

Documentação de referência:
- `ARCHITECTURE_HTTP_SERVICES.md` - Design completo
- `MCP_CONSTRUCTION_GUIDE.md` - Especificação
- `.mcp-http.json` - Mapa de portas
- `MCP_SERVICES_README.md` - Quick start

---

## 🔧 Configuração de Rede

**Pré-requisitos:**

1. **Conectividade:** Todas as máquinas devem alcançar `claude-dev:8000`
   ```bash
   curl http://claude-dev:8000/services
   # ou
   curl http://34.193.217.90:8000/services
   ```

2. **DNS/Hosts:** Configure para resolver `claude-dev`
   ```bash
   # /etc/hosts (Linux/Mac) ou C:\Windows\System32\drivers\etc\hosts (Windows)
   34.193.217.90  claude-dev
   ```

3. **Firewall:** Abra portas 8000, 7100-7116, 7118-7125 na VM
   ```bash
   sudo ufw allow 8000:7125/tcp
   ```

---

## 📊 Descoberta de MCPs

**Automático via Registry:**

```bash
# Todos os MCPs
curl http://claude-dev:8000/services | jq

# Específico
curl http://claude-dev:8000/services/config-mcp | jq

# Estatísticas
curl http://claude-dev:8000/stats | jq
```

**Config gerada automaticamente:**

```bash
# Para Claude Code
curl http://claude-dev:8000/config | jq
```

---

## 🔐 Segurança & Governança

### Princípios

1. **Compartilhado = Responsabilidade coletiva**
   - Alertar sobre mudanças em `docker-compose-system.yml`
   - Revisar PRs que tocam MCPs
   - Documentar breaking changes

2. **Acesso controlado**
   - Wrapper roda com permissões do usuário
   - Cada usuário autenticado via `TWIN_TOKEN`
   - Audit log em `audit-mcp`

3. **Versionamento**
   - MCPs versionados no repo
   - Mudanças de schema = nova versão
   - Suportar múltiplas versões simultaneously

### Auditoria

```bash
# Verificar quem usou qual ferramenta
curl http://claude-dev:7105/mcp/tools/call \
  -d '{"method": "tools/call", "params": {"name": "search_logs", "arguments": {"user": "caiog"}}}'
```

---

## 📈 Escalando para Novos Projetos

### Cenário 1: Novo projeto usa os mesmos MCPs

```bash
git clone https://github.com/seu-org/platform-devs.git
cd novo-projeto
cp ../platform-devs/mcp-http-wrapper.py ./
# Configure .claude/settings.json
```

### Cenário 2: Novo projeto precisa de MCPs customizados

```bash
# Criar novo MCP na VM claude-dev
cd platform-devs
# Adicionar novo-mcp-server/
# Registrar em docker-compose-system.yml
# Rebuild e restart

docker compose -f docker-compose-system.yml build
docker compose -f docker-compose-system.yml up -d
```

### Cenário 3: Múltiplas instâncias de MCPs (por ambiente)

```bash
# Claude-dev (produção)
docker compose -f docker-compose-system.yml up -d

# Claude-staging (staging)
docker compose -f docker-compose-system-staging.yml up -d
  (porta 8001, MCPs 7200-7225)

# Configure wrapper para apontar para staging
MCP_REGISTRY_URL = "http://claude-staging:8001"
```

---

## 📝 Onboarding Novo Membro

**Checklist de onboarding:**

- [ ] Acesso SSH a `claude-dev` (para verificar)
- [ ] Git clone `platform-devs`
- [ ] Executar `install-mcp-wrapper.py` ou `.bat`
- [ ] Reiniciar Claude Code
- [ ] Teste: pergunta ao Claude "What tools are available?"
- [ ] Documentação: ler `MCP_SERVICES_README.md`
- [ ] Suporte: chamar no Slack #platform-devs

**Script de onboarding:**

```bash
#!/bin/bash
# onboard-mcp.sh

echo "🚀 MCP Onboarding"
echo "================="

# Check prerequisites
python3 --version || { echo "❌ Python3 not found"; exit 1; }

# Clone repo
git clone https://github.com/seu-org/platform-devs.git
cd platform-devs

# Run installer
python3 install-mcp-wrapper.py

echo ""
echo "✅ Setup completo!"
echo "📖 Leia: MCP_SERVICES_README.md"
echo "🔧 Configure: ~/.claude/settings.json"
echo "🚀 Reinicie: Claude Code Desktop"
```

---

## 🔄 Atualizações & Manutenção

### Quando fazer deploy de novo MCP

```bash
# 1. Commit no repo
git add nova-mcp/
git commit -m "feat: add nova-mcp"
git push

# 2. Na VM claude-dev
git pull
docker compose -f docker-compose-system.yml build nova-mcp
docker compose -f docker-compose-system.yml up -d nova-mcp

# 3. Verificar
curl http://localhost:8000/services | jq '.[] | select(.name == "nova-mcp")'

# 4. Anunciar no Slack
```

### Quando atualizar versão do MCP

```bash
# Se quebra compatibilidade
# 1. Versionar schema (v2/v3)
# 2. Manter compatibilidade retroativa
# 3. Anunciar deprecação com prazo

# Se compatível
# 1. Deploy normalmente
# 2. Notificar usuários de melhoria
```

### Monitoramento

```bash
# Health check
curl http://claude-dev:8000/health

# Métricas
curl http://claude-dev:8000/stats

# Logs
docker compose -f docker-compose-system.yml logs -f config-mcp
```

---

## 📞 Suporte & Troubleshooting

### "Não consegue conectar aos MCPs"

```bash
# 1. Verificar hostname
ping claude-dev

# 2. Se não resolver, usar IP
# Edite: ~/.claude/settings.json
# Mude: "http://claude-dev:8000" → "http://34.193.217.90:8000"

# 3. Verificar firewall
curl http://claude-dev:8000/services -v

# 4. Se timeout, MCPs podem estar down
# Contate: #platform-ops
```

### "Ferramentas não aparecem"

```bash
# 1. Reiniciar Claude Code
# 2. Verificar logs
tail -f /tmp/mcp-wrapper.log

# 3. Testar wrapper manualmente
python3 mcp-http-wrapper.py

# 4. Se ainda não funcionar
# Execute: ./install-mcp-wrapper.py novamente
```

---

## 📚 Referências

| Documento | Público | Propósito |
|-----------|---------|----------|
| `.mcp-http.json` | Todos | Mapa de portas/endpoints |
| `MCP_SERVICES_README.md` | Desenvolvedores | Quick start |
| `MCP_WRAPPER_SETUP.md` | Desenvolvedores | Guia detalhado |
| `ARCHITECTURE_HTTP_SERVICES.md` | Arquitetura | Design e decisões |
| `MCP_CONSTRUCTION_GUIDE.md` | Desenvolvedores MCP | Como criar novo MCP |
| `docker-compose-system.yml` | DevOps/Infra | Infraestrutura |

---

## ✅ Checklist de Compartilhamento

Antes de fazer público:

- [ ] MCPs rodando em HTTP (docker-compose-system.yml)
- [ ] Registry funcional (porta 8000)
- [ ] Wrapper testado e funcional
- [ ] Documentação completa
- [ ] Setup automatizado (.py/.bat)
- [ ] Testes de integração
- [ ] Guia de troubleshooting
- [ ] Suporte definido (#channel ou person)
- [ ] Processo de onboarding documentado
- [ ] Versionamento de MCPs definido

---

**Status:** ✅ Pronto para compartilhamento
**Próximos passos:** Anunciar no time + onboard primeiro usuário
