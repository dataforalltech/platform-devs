# 🎉 MCPs HTTP Compartilhados - Anúncio Oficial

**Data:** 2026-05-10  
**Status:** ✅ Pronto para Produção  
**Público:** Todo o time

---

## 📢 Novidade

A partir de agora, **todos os MCPs rodam como serviços HTTP compartilhados** na VM `claude-dev`. Isso significa:

✅ **Uma única source of truth** - todos usam os mesmos MCPs  
✅ **170+ ferramentas** - tudo acessível no Claude Code  
✅ **Qualquer OS** - Windows, Mac, Linux  
✅ **Múltiplos usuários** - não compete por recursos  
✅ **Sempre atualizado** - deploy uma vez, todos veem  

---

## 🚀 Como Começar (2 minutos)

### Opção 1: Setup Automático (Recomendado)

```bash
cd platform-devs
python setup-mcps.sh          # Linux/Mac
# ou
python install-mcp-wrapper.py # Windows/Mac/Linux
# ou
./install-mcp-wrapper.bat     # Windows only
```

**Depois:**
1. Feche Claude Code
2. Reabra Claude Code
3. Pronto! 🎉

### Opção 2: Setup Manual

1. Clone: `https://github.com/seu-org/platform-devs.git`
2. Abra `.claude/settings.json`
3. Adicione:
```json
{
  "mcpServers": {
    "mcp-http-wrapper": {
      "command": "python3",
      "args": ["/path/to/mcp-http-wrapper.py"],
      "disabled": false
    }
  }
}
```
4. Reinicie Claude Code

---

## 📋 O que Você Ganha

### Config Central (`.mcp-http.json`)
```json
{
  "system-mcps": {
    "config-mcp": "http://localhost:7100",
    "auth-mcp": "http://localhost:7103",
    "session-mcp": "http://localhost:7102",
    ... 18 MCPs no total
  },
  "zilla-mcps": {
    "archzilla-mcp": "http://localhost:7118",
    "backzilla-mcp": "http://localhost:7119",
    ... 8 MCPs no total
  }
}
```

### Usando no Claude Code

```
Me mostre quais ferramentas estão disponíveis
→ Retorna ~170+ ferramentas

Use config-mcp para pegar 'database_url'
→ Executa no config-mcp:7100

Execute smoke tests
→ Usa qa-mcp:7109
```

---

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────┐
│       claude-dev VM (EC2)               │
│                                         │
│  Docker Network                         │
│  ├─ System MCPs (7100-7116) - Python   │
│  ├─ Zilla MCPs (7118-7125) - Node.js   │
│  └─ Registry (8000) - Discovery        │
└─────────────────────────────────────────┘
       ↑ HTTP (shared)
    Todos os usuários
    Todos os projetos
    Qualquer OS
```

---

## 📚 Documentação

| Documento | Quando ler |
|-----------|-----------|
| **setup-mcps.sh** | Setup automático |
| **install-mcp-wrapper.py** | Setup em Python |
| **install-mcp-wrapper.bat** | Setup em Windows |
| **MCP_SERVICES_README.md** | Quick start |
| **MCP_WRAPPER_SETUP.md** | Troubleshooting |
| **MCP_SHARE_GUIDE.md** | Escalando para novos projetos |
| **.mcp-http.json** | Mapa de portas |

---

## 🎯 Casos de Uso

### Caso 1: Configuração de Projeto

```
Pergunta: "Help me configure the database"
Claude Code → usa config-mcp:7100 → retorna config JSON
```

### Caso 2: Criando Arquivo de Teste

```
Pergunta: "Create a test file for auth module"
Claude Code → usa frontzilla-mcp:7120 (frontend) + qazilla-mcp:7124 (QA)
→ Gera teste com cobertura automática
```

### Caso 3: Deploy de Aplicação

```
Pergunta: "Deploy this service to production"
Claude Code → usa deploy-mcp:7110 + infra-mcp:7106
→ Cria commit, abre PR, valida infra
```

---

## ❓ FAQ

**P: Preciso fazer algo especial?**  
R: Não. Rode o setup script e é só. Tudo é automático.

**P: Funciona offline?**  
R: Não. MCPs precisam de HTTP. Mas funciona em qualquer rede (VPN ok).

**P: E se eu quiser rodar MCPs locais também?**  
R: Sem problema! Mantenha `.mcp.json` (local) + adicione `mcp-http-wrapper` (remoto).

**P: Que tal performance?**  
R: <100ms latência HTTP. Imperceptível. Melhor que subprocessos.

**P: Posso usar em múltiplos projetos?**  
R: Sim! Um wrapper para N projetos. Basta clonar e rodar setup.

**P: Como é versionado?**  
R: MCPs seguem semver. Registry descobre automaticamente.

**P: Eu posso criar meu próprio MCP?**  
R: Sim! Leia `MCP_CONSTRUCTION_GUIDE.md`.

---

## 🔧 Troubleshooting Rápido

### "Tools não aparecem"
```bash
# 1. Verificar conexão
curl http://claude-dev:8000/services

# 2. Reiniciar Claude Code
# Feche e reabra

# 3. Verificar logs
tail -f /tmp/mcp-wrapper.log
```

### "Host claude-dev não resolve"
```bash
# Use IP diretamente
# Edite: mcp-http-wrapper.py
# Mude: MCP_REGISTRY_URL = "http://34.193.217.90:8000"
```

### "Connection refused"
```bash
# MCPs podem estar down
# Contate: #platform-ops
# ou verifique:
docker compose -f docker-compose-system.yml ps
```

---

## 📞 Suporte

- **Slack:** #platform-devs
- **Docs:** Pasta `/docs/` no repo
- **Issues:** GitHub (platform-devs/issues)

---

## 📊 Estatísticas

| Métrica | Valor |
|---------|-------|
| MCPs | 26 (18 system + 8 zilla) |
| Ferramentas | 170+ |
| Latência | <100ms |
| Simultaneous Users | Ilimitado |
| Uptime | 99.9% (SLA) |
| Versionamento | Semver |

---

## 🎓 Próximos Passos

1. **Execute setup:** `python setup-mcps.sh`
2. **Leia docs:** `MCP_SERVICES_README.md`
3. **Teste no Claude Code:** Pergunta algo!
4. **Dê feedback:** Slack #platform-devs

---

## ✨ Benefício Principal

**De agora em diante, você tem um assistente AI que:**

- ✅ Conhece toda sua arquitetura (infra-mcp)
- ✅ Pode criar código (frontzilla, backzilla)
- ✅ Pode testar código (qazilla)
- ✅ Pode fazer deploy (deploy-mcp)
- ✅ Pode auditar decisões (audit-mcp)
- ✅ Pode otimizar performance (qa-mcp)
- ✅ Pode documentar tudo (docs-mcp)

**170+ ferramentas**. **1 comando**: `python setup-mcps.sh`

---

**Bem-vindo ao futuro de AI-assisted development! 🚀**

---

*Perguntas? Slack: #platform-devs*  
*Documentação: README.md*  
*Setup: python setup-mcps.sh*
