# PASSO 4: Deploy para Produção — 4 MCPs + Zilla Integration

## Objetivo
Deploy das 4 MCPs compiladas para produção com:
1. Merge de 4 PRs para main
2. Deploy de 4 MCPs em portas 7110-7113
3. Registro em services-mcp
4. Health check e validação de ecossistema

---

## Pré-requisitos

✅ PASSO 1: 4 PRs criadas (PR #3-6)
✅ PASSO 2: ZillaIntegration.ts + padrões de integração
✅ PASSO 3: Teste E2E OAuth2 concluído com sucesso
✅ Branches: feature/knowledge-base-mcp, feature/cross-zilla-validators, feature/quality-gates-system, feature/zilla-observatory

---

## Passo 4.1: Merge das 4 PRs para main

### Status das PRs

| PR | Título | Branch | Status |
|----|--------|--------|--------|
| #3 | Phase 1 — Knowledge Base MCP | feature/knowledge-base-mcp | ⏳ Ready for merge |
| #4 | Phase 2 — Cross-Zilla Validators | feature/cross-zilla-validators | ⏳ Ready for merge |
| #5 | Phase 3 — Quality Gates System | feature/quality-gates-system | ⏳ Ready for merge |
| #6 | Phase 4 — Zilla Observatory | feature/zilla-observatory | ⏳ Ready for merge |

### Processo de Merge

```bash
# 1. Atualizar main localmente
git checkout main
git pull origin main

# 2. Merge de cada PR (já verificadas em CI)
gh pr merge 3 --squash --auto
gh pr merge 4 --squash --auto
gh pr merge 5 --squash --auto
gh pr merge 6 --squash --auto

# 3. Verificar resultado
git log main -1 --oneline # Deve mostrar último merge
git branch -v | grep feature/ # Deve mostrar branches merged
```

**Resultado Esperado:**
- 4 commits novos em main
- 4 branches fechadas
- main pronto para tag de release

---

## Passo 4.2: Tag de Release e Changelog

```bash
# 1. Criar tag v1.0.0-ecosystem
git tag -a v1.0.0-ecosystem -m "Release: Phase 1-4 MCPs (Knowledge Base, Validators, Quality Gates, Observatory)"
git push origin v1.0.0-ecosystem

# 2. Gerar changelog
gh release create v1.0.0-ecosystem \
  --title "Phase 1-4 MCPs — Complete Ecosystem" \
  --notes "
## Features

### Phase 1 — Knowledge Base MCP (6 tools)
- Documentação centralizada
- SQLite indexing
- 20+ testes

### Phase 2 — Cross-Zilla Validators (18 validators)
- Validação de handoffs
- 18 validadores específicos
- 40+ testes

### Phase 3 — Quality Gates System (10 gates)
- 10 gates automáticas de qualidade
- Bloqueio de progresso até aprovação
- 30+ testes

### Phase 4 — Zilla Observatory (10 tools)
- Observabilidade em tempo real
- Dashboards por Zilla
- Alertas de anomalias
- 35+ testes

## Integration

- ZillaIntegration.ts: Padrão unificado para todos os 8 Zillas
- Handoff validation automática
- Metrics agregadas no Observatory
- E2E OAuth2 test: ✅ ALL GATES PASSED
"
```

---

## Passo 4.3: Build & Deploy dos 4 MCPs

### Estrutura de Portas

| MCP | Porta | Tipo | Status |
|-----|-------|------|--------|
| knowledge-base-mcp | 7110 | Docker | ⏳ Build & Deploy |
| cross-zilla-validators | 7111 | Docker | ⏳ Build & Deploy |
| quality-gates-system | 7112 | Docker | ⏳ Build & Deploy |
| zilla-observatory | 7113 | Docker | ⏳ Build & Deploy |

### Build Docker

```bash
# 1. Build imagens para ACR
cd /home/dev/repos/platform-devs

# Knowledge Base MCP
docker build -f knowledge-base-mcp/Dockerfile \
  -t platform-knowledge-base-mcp:v1.0.0 \
  knowledge-base-mcp/

# Cross-Zilla Validators
docker build -f cross-zilla-validators/Dockerfile \
  -t platform-validators-mcp:v1.0.0 \
  cross-zilla-validators/

# Quality Gates System
docker build -f quality-gates-system/Dockerfile \
  -t platform-quality-gates-mcp:v1.0.0 \
  quality-gates-system/

# Zilla Observatory
docker build -f zilla-observatory/Dockerfile \
  -t platform-observatory-mcp:v1.0.0 \
  zilla-observatory/

# 2. Push para ACR (assumindo credenciais configuradas)
docker push platform-knowledge-base-mcp:v1.0.0
docker push platform-validators-mcp:v1.0.0
docker push platform-quality-gates-mcp:v1.0.0
docker push platform-observatory-mcp:v1.0.0
```

### Deploy com Docker Compose (Local/Dev)

```bash
# 1. Criar docker-compose.prod.yml
cat > docker-compose.prod.yml << 'EOF'
version: '3.8'

services:
  knowledge-base-mcp:
    image: platform-knowledge-base-mcp:v1.0.0
    ports:
      - "7110:7110"
    environment:
      PORT: 7110
      DB_PATH: /data/knowledge-base.db
      LOG_LEVEL: info
    volumes:
      - ./data/knowledge-base:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7110/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  cross-zilla-validators:
    image: platform-validators-mcp:v1.0.0
    ports:
      - "7111:7111"
    environment:
      PORT: 7111
      DB_PATH: /data/validators.db
      LOG_LEVEL: info
    volumes:
      - ./data/validators:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7111/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  quality-gates-system:
    image: platform-quality-gates-mcp:v1.0.0
    ports:
      - "7112:7112"
    environment:
      PORT: 7112
      DB_PATH: /data/gates.db
      LOG_LEVEL: info
    volumes:
      - ./data/gates:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7112/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  zilla-observatory:
    image: platform-observatory-mcp:v1.0.0
    ports:
      - "7113:7113"
    environment:
      PORT: 7113
      DB_PATH: /data/observatory.db
      LOG_LEVEL: info
    volumes:
      - ./data/observatory:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7113/health"]
      interval: 30s
      timeout: 10s
      retries: 3

networks:
  default:
    driver: bridge
EOF

# 2. Deploy
docker-compose -f docker-compose.prod.yml up -d

# 3. Verificar logs
docker-compose -f docker-compose.prod.yml logs -f
```

---

## Passo 4.4: Registrar em services-mcp

```bash
# 1. Registrar 4 MCPs no services-mcp
curl -X POST http://localhost:7102/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "knowledge-base-mcp",
    "host": "localhost",
    "port": 7110,
    "type": "docker",
    "environment": "production",
    "health_path": "/health",
    "tags": ["mcp", "phase-1", "ecosystem"]
  }'

curl -X POST http://localhost:7102/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "cross-zilla-validators",
    "host": "localhost",
    "port": 7111,
    "type": "docker",
    "environment": "production",
    "health_path": "/health",
    "tags": ["mcp", "phase-2", "ecosystem"]
  }'

curl -X POST http://localhost:7102/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "quality-gates-system",
    "host": "localhost",
    "port": 7112,
    "type": "docker",
    "environment": "production",
    "health_path": "/health",
    "tags": ["mcp", "phase-3", "ecosystem"]
  }'

curl -X POST http://localhost:7102/services \
  -H "Content-Type: application/json" \
  -d '{
    "name": "zilla-observatory",
    "host": "localhost",
    "port": 7113,
    "type": "docker",
    "environment": "production",
    "health_path": "/health",
    "tags": ["mcp", "phase-4", "ecosystem"]
  }'
```

**Ou via MCP client:**

```bash
# Script para registrar via services-mcp
mcp-client services-mcp register_service \
  --name knowledge-base-mcp \
  --host localhost \
  --port 7110 \
  --type docker \
  --environment production

# ... repetir para os outros 3
```

---

## Passo 4.5: Health Check de Todos os MCPs

```bash
# 1. Check individual
curl http://localhost:7110/health  # knowledge-base-mcp
curl http://localhost:7111/health  # cross-zilla-validators
curl http://localhost:7112/health  # quality-gates-system
curl http://localhost:7113/health  # zilla-observatory

# 2. Check agregado via services-mcp
curl http://localhost:7102/services/health | jq '.[] | {name, status}'

# Expected output:
# {
#   "name": "knowledge-base-mcp",
#   "status": "healthy"
# }
# {
#   "name": "cross-zilla-validators",
#   "status": "healthy"
# }
# {
#   "name": "quality-gates-system",
#   "status": "healthy"
# }
# {
#   "name": "zilla-observatory",
#   "status": "healthy"
# }
```

---

## Passo 4.6: Validação de Ecossistema

```bash
# 1. Validar que 4 MCPs estão respondendo a requisições
curl -X POST http://localhost:7110/tools/list | jq '.tools | length'
# Expected: 6 (knowledge-base-mcp tem 6 tools)

curl -X POST http://localhost:7111/tools/list | jq '.tools | length'
# Expected: 18 (validators tem 18 validators)

curl -X POST http://localhost:7112/tools/list | jq '.tools | length'
# Expected: 10 (quality-gates tem 10 tools)

curl -X POST http://localhost:7113/tools/list | jq '.tools | length'
# Expected: 10 (observatory tem 10 tools)

# 2. Teste de integração: chamar validator from knowledge-base-mcp
curl -X POST http://localhost:7111/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "validate_completeness",
    "arguments": {
      "from_zilla": "ProductZilla",
      "to_zilla": "ArchZilla",
      "payload": {"spec_id": "oauth2_v1"}
    }
  }' | jq '.passed'

# 3. Registrar metrics no observatory
curl -X POST http://localhost:7113/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "report_metrics",
    "arguments": {
      "zilla": "ProductZilla",
      "metrics": {"feature": "OAuth2", "status": "deployed"}
    }
  }'
```

---

## Passo 4.7: Atualizar .mcp.json Global

```bash
# 1. Atualizar configuração global de MCPs
cat >> /home/dev/.mcp.json << 'EOF'
{
  "knowledge-base-mcp": {
    "command": "docker",
    "args": ["start", "knowledge-base-mcp"],
    "port": 7110,
    "env": {}
  },
  "cross-zilla-validators": {
    "command": "docker",
    "args": ["start", "cross-zilla-validators"],
    "port": 7111,
    "env": {}
  },
  "quality-gates-system": {
    "command": "docker",
    "args": ["start", "quality-gates-system"],
    "port": 7112,
    "env": {}
  },
  "zilla-observatory": {
    "command": "docker",
    "args": ["start", "zilla-observatory"],
    "port": 7113,
    "env": {}
  }
}
EOF
```

---

## Passo 4.8: Verificação Final — Dashboard

```bash
# 1. Observatory Dashboard
open http://localhost:7113/dashboard

# Expected: Tela mostrando:
# - 8 Zillas online ✅
# - Feature OAuth2 100% complete ✅
# - All gates passed ✅
# - Real-time metrics streaming

# 2. Services Status
open http://localhost:7102/status

# Expected:
# Services Online: 35/35 ✅
# - 18 MCPs online
# - 17 application services
# - 0 offline

# 3. Documentation Index
open http://localhost:7110/docs

# Expected: Full documentation of all 4 MCPs
```

---

## Checklist Final — PASSO 4

- [ ] 4 PRs merged para main
- [ ] Release tag v1.0.0-ecosystem criada
- [ ] 4 MCPs buildados (Docker images)
- [ ] 4 MCPs deployados (portas 7110-7113)
- [ ] 4 MCPs registrados em services-mcp
- [ ] Health checks passando (4/4) ✅
- [ ] Tools acessíveis (36 tools total) ✅
- [ ] Integração de validadores funcionando ✅
- [ ] Observatory mostrando métricas ✅
- [ ] E2E OAuth2 ainda passando com novos MCPs ✅

---

## Status Final Esperado

```
════════════════════════════════════════════════════════════════════════════════
                         🚀 PLATFORM ECOSYSTEM READY
════════════════════════════════════════════════════════════════════════════════

✅ PASSO 1: 4 PRs Merged (main branch)
✅ PASSO 2: 8 Zillas Integrados (ZillaIntegration.ts ativo)
✅ PASSO 3: E2E OAuth2 100% Completo (all gates passed)
✅ PASSO 4: Deploy em Produção (4 MCPs rodando)

────────────────────────────────────────────────────────────────────────────────
Ecosystem Status:
────────────────────────────────────────────────────────────────────────────────

MCPs Online (4/4):
  ✅ knowledge-base-mcp (port 7110) — 6 tools
  ✅ cross-zilla-validators (port 7111) — 18 validators
  ✅ quality-gates-system (port 7112) — 10 gates
  ✅ zilla-observatory (port 7113) — 10 tools

Zillas Online (8/8):
  ✅ ProductZilla — Feature specs ready
  ✅ ArchZilla — Architecture design ready
  ✅ BackZilla — API implementation ready
  ✅ FrontZilla-PixelFera — UI design ready
  ✅ OpsZilla — Deployment ready
  ✅ QAZilla — Testing ready
  ✅ SecZilla — Security approval ready
  ✅ POZilla — Coordination ready

Services: 35/35 Online ✅
Quality Gates: 14/14 PASSED ✅
Features: 100% Observable ✅

════════════════════════════════════════════════════════════════════════════════
READY FOR PRODUCTION FEATURES
════════════════════════════════════════════════════════════════════════════════
```

---

## Próximos Passos (Opcional)

1. **Kubernetes Deployment** (se required):
   - Gerar helm charts para 4 MCPs
   - Deploy em staging cluster
   - Auto-scaling policies

2. **CI/CD Integration**:
   - Auto-deploy on main branch merge
   - Automated health checks
   - Rollback triggers

3. **Monitoring & Alerting**:
   - Integrar com Prometheus/Grafana
   - Set up PagerDuty escalations
   - SLA tracking

4. **Documentation**:
   - API docs (Swagger/OpenAPI)
   - Integration guides
   - Troubleshooting runbooks

---

## Rollback Plan (se necessário)

```bash
# 1. Stop new MCPs
docker-compose -f docker-compose.prod.yml down

# 2. Revert main branch
git revert HEAD~3 # Reverte últimos 3 merges
git push origin main

# 3. Deploy versão anterior
git checkout v0.9.0
# ... redeploy via CI/CD

# 4. Notificar time
# Via Observatory alerts + Slack
```

---

## Conclusão

Ao completar PASSO 4, teremos:

✅ 4 MCPs compilados, testados e em produção
✅ 8 Zillas completamente integrados
✅ E2E OAuth2 feature pronta para produção
✅ Observable mostrando toda a pipeline em tempo real
✅ Zero downtime durante deploy
✅ Rollback plan pronto se necessário

**Ecossistema de Zillas completamente funcional e escalável.**
