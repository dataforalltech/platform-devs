# Quick Start — Executar Passos 2-4

## Status Atual

✅ PASSO 1: 4 PRs criadas (PR #3, #4, #5, #6)
✅ Documentação: Completa
⏳ PASSO 2-4: Prontos para execução

---

## PASSO 2: Integrar 8 Zillas (30 min)

### Atalho: Copiar ZillaIntegration.ts

```bash
cd /home/dev/repos/platform-devs

# Já criado em:
ls -la ZillaIntegration.ts

# Adicionar import em cada Zilla server.ts:
for zilla in archzilla-mcp-server backzilla-mcp-server frontzilla-pixelfera-mcp-server opszilla-mcp-server pozilla-mcp-server productzilla-mcp-server qa-mcp-server seczilla-mcp-server; do
  echo "Atualizando $zilla..."
  # Adicionar no início do arquivo:
  # import ZillaIntegration from '../../ZillaIntegration';
done
```

### Exemplo: ProductZilla

Abrir `/productzilla-mcp-server/src/server.ts` e adicionar:

```typescript
import ZillaIntegration from '../../ZillaIntegration';

// Em generateFeatureSpec():
async generateFeatureSpec(requirement: string) {
  const zillaInt = new ZillaIntegration('ProductZilla');
  return zillaInt.executeWorkflow(
    'generate_feature_spec',
    async () => {
      const spec = await this.generateSpec(requirement);
      return { spec_id: spec.id, title: spec.title };
    },
    []
  );
}
```

### Verificar Integração

```bash
# Compilar cada Zilla
npm run build

# Testar imports
npm run test -- --testPathPattern="integration"

# Commit
git add .
git commit -m "feat: integrate knowledge-base, validators, quality-gates, observatory MCPs"
git push origin feature/zilla-integration
```

---

## PASSO 3: Teste E2E OAuth2 (1-2 horas)

### Executar Feature Completa

```bash
# Abrir 8 terminais ou tmux sessions

# Terminal 1: ProductZilla — Spec
npm run zilla:product -- --task oauth2_spec

# Terminal 2: POZilla — Breakdown
npm run zilla:po -- --task breakdown --spec oauth2_v1

# Terminals 3-6: Paralelo (Arch, Back, Front, Ops)
npm run zilla:arch -- --task design --spec oauth2_v1 &
npm run zilla:back -- --task implement --blueprint oauth2_arch_v1 &
npm run zilla:front -- --task design-ui --spec oauth2_v1 &
npm run zilla:ops -- --task deploy --api oauth2_api_v1 &
wait

# Terminal 7: QAZilla — Tests
npm run zilla:qa -- --task e2e --spec oauth2_v1 --api oauth2_api_v1

# Terminal 8: SecZilla — Security
npm run zilla:sec -- --task threat-model --blueprint oauth2_arch_v1

# Terminal 9: POZilla — Finalize
npm run zilla:po -- --task finalize --feature oauth2_v1

# Verificar Observatory
open http://localhost:7113/dashboard/oauth2_integration
```

### Expected Output

```
✅ ProductZilla: spec_id=oauth2_v1 (8 stories, 34 points)
✅ POZilla: breakdown_complete
✅ ArchZilla: blueprint_id=oauth2_arch_v1
✅ BackZilla: api_id=oauth2_api_v1 (5 endpoints)
✅ FrontZilla: components=4, accessibility_passed
✅ OpsZilla: staging_deployed, performance_ok
✅ QAZilla: e2e_tests_passed (8/8, 92% coverage)
✅ SecZilla: threat_model_complete, no_critical_issues
✅ POZilla: feature_ready_for_release

Observatory Dashboard: 14/14 gates PASSED ✅
```

---

## PASSO 4: Deploy para Produção (1 hora)

### 4.1 — Merge PRs

```bash
cd /home/dev/repos/platform-devs
git checkout main
git pull origin main

# Merge das 4 PRs
gh pr merge 3 --squash --auto
gh pr merge 4 --squash --auto
gh pr merge 5 --squash --auto
gh pr merge 6 --squash --auto

# Verificar
git log main -1 --oneline
```

### 4.2 — Docker Build

```bash
# Build 4 imagens
docker build -f knowledge-base-mcp/Dockerfile \
  -t platform-knowledge-base-mcp:v1.0.0 \
  knowledge-base-mcp/

docker build -f cross-zilla-validators/Dockerfile \
  -t platform-validators-mcp:v1.0.0 \
  cross-zilla-validators/

docker build -f quality-gates-system/Dockerfile \
  -t platform-quality-gates-mcp:v1.0.0 \
  quality-gates-system/

docker build -f zilla-observatory/Dockerfile \
  -t platform-observatory-mcp:v1.0.0 \
  zilla-observatory/
```

### 4.3 — Deploy

```bash
# Deploy com docker-compose
docker-compose -f docker-compose.prod.yml up -d

# Verificar
docker-compose -f docker-compose.prod.yml ps

# Logs
docker-compose -f docker-compose.prod.yml logs -f knowledge-base-mcp
```

### 4.4 — Health Checks

```bash
# Verificar 4 MCPs
curl http://localhost:7110/health && echo " ✅ knowledge-base"
curl http://localhost:7111/health && echo " ✅ validators"
curl http://localhost:7112/health && echo " ✅ quality-gates"
curl http://localhost:7113/health && echo " ✅ observatory"
```

### 4.5 — Registrar em services-mcp

```bash
# Registrar automaticamente
for port in 7110 7111 7112 7113; do
  curl -X POST http://localhost:7102/services/register \
    -H "Content-Type: application/json" \
    -d "{\"port\": $port, \"environment\": \"production\"}"
done

# Verificar
curl http://localhost:7102/services/health | jq '.'
```

### 4.6 — Final Dashboard

```bash
# Abrir dashboard
open http://localhost:7113/dashboard

# Expected:
# - 8 Zillas: Online ✅
# - 35 Serviços: Online ✅
# - Feature OAuth2: 100% Complete ✅
# - Quality Gates: 14/14 PASSED ✅
```

---

## Troubleshooting

### Zilla não conecta a MCP

```bash
# Verificar se porta está aberta
lsof -i :7110  # knowledge-base

# Verificar se MCP está respondendo
curl http://localhost:7110/health -v

# Verificar logs do MCP
docker logs knowledge-base-mcp -f
```

### Test E2E falhando

```bash
# Verificar validadores
curl -X POST http://localhost:7111/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "validate_completeness",
    "arguments": {
      "from_zilla": "ProductZilla",
      "to_zilla": "ArchZilla",
      "payload": {"spec_id": "test"}
    }
  }' | jq '.'

# Verificar gates
curl -X POST http://localhost:7112/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "check_gates",
    "arguments": {"component": "oauth2_api"}
  }' | jq '.'
```

### Observatory não mostrando progresso

```bash
# Verificar se está recebendo métricas
curl http://localhost:7113/metrics | jq '.'

# Verificar database
sqlite3 /data/observatory.db ".tables"
sqlite3 /data/observatory.db "SELECT COUNT(*) FROM metrics;"
```

---

## Timeline Estimado

| Passo | Duração | Crítico |
|-------|---------|---------|
| PASSO 2 | 30 min | ✅ |
| PASSO 3 | 1-2 h | ✅ |
| PASSO 4 | 1 h | ✅ |
| **Total** | **2.5-3.5 h** | **~1 dia** |

---

## Checklist Final

Antes de considerar "PRONTO PARA PRODUÇÃO":

- [ ] PASSO 2: Todos os 8 Zillas compilam sem erros
- [ ] PASSO 2: ZillaIntegration import funciona
- [ ] PASSO 3: E2E OAuth2 executa até o fim
- [ ] PASSO 3: Observatory mostra 100% progress
- [ ] PASSO 3: 14/14 gates PASSED
- [ ] PASSO 4: 4 PRs merged para main
- [ ] PASSO 4: 4 MCPs deployados (7110-7113)
- [ ] PASSO 4: Health checks passando (4/4)
- [ ] PASSO 4: Dashboard observable acessível
- [ ] PASSO 4: 44 tools disponíveis (6+18+10+10)

---

## Próximo Status Check

Após completar todos os 4 passos, você terá:

✅ Ecossistema de 8 Zillas plenamente coordenado
✅ 4 MCPs em produção (portas 7110-7113)
✅ Validação automática de handoffs
✅ Quality gates bloqueantes
✅ Observabilidade em tempo real
✅ E2E OAuth2 feature completa e pronta

**STATUS: PRODUCTION READY** 🚀

---

## Suporte

Documentação completa em:
- `/ZILLA_INTEGRATION_EXAMPLES.md` — Padrão por Zilla
- `/PASSO_3_E2E_OAUTH2_TEST.md` — Detalhes do teste E2E
- `/PASSO_4_DEPLOY_PRODUCTION.md` — Detalhes do deployment
- `/EXECUTION_SUMMARY.md` — Visão geral completa

Dúvidas? Consulte os arquivos acima ou abra uma issue com `[four-steps]` tag.
