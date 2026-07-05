# DevTeam MCP Integration Pattern

## Opção B — Direct Integration

Cada DevTeam MCP agora orquestra com outras MCPs para criar artefatos validados e rastreados.

---

## Padrão Implementado em Product-Owner

### 1. Importar Cliente Compartilhado

```typescript
import { mcpClient } from '@platform/mcp-client';
```

### 2. Integração em Tools

#### Exemplo: `generate_epic()`

```typescript
case 'generate_epic': {
  const epic = { /* ... epic data ... */ };
  
  // Orquestra com test-mcp
  const testPlanResult = await mcpClient.callTestTool('create_test_plan', {
    title: `Test Plan: ${epic.title}`,
    scope: `Testing ${epic.title} epic`,
  });
  
  return JSON.stringify({
    epic,
    test_plan: testPlanResult,
    status: 'created_with_test_plan',
  }, null, 2);
}
```

#### Exemplo: `generate_user_stories()`

```typescript
case 'generate_user_stories': {
  const stories = [ /* ... */ ];
  
  // Valida com qa-mcp
  const validation = await mcpClient.callQATool('run_linter', {
    repo_path: input.feature,
  });
  
  // Gera cenários com test-mcp
  const scenarios = await mcpClient.callTestTool('generate_scenarios', {
    plan_id: 'current_plan',
    category: 'rest_api',
  });
  
  return JSON.stringify({
    stories,
    validation,
    test_scenarios: scenarios,
    status: 'generated_with_validation',
  }, null, 2);
}
```

#### Exemplo: `validate_story_readiness()`

```typescript
case 'validate_story_readiness': {
  const validation = { /* ... */ };
  
  // Double-check com qa-mcp e test-mcp
  const qaValidation = await mcpClient.callQATool('run_linter', {
    repo_path: input.story_title,
  });
  
  const testValidation = await mcpClient.callTestTool('double_check', {
    plan_id: 'current_plan',
  });
  
  return JSON.stringify({
    ...validation,
    qa_validation: qaValidation,
    test_validation: testValidation,
    final_status: qaValidation.success ? 'READY' : 'NEEDS_REVIEW',
  }, null, 2);
}
```

---

## Fluxo Completo: Product-Owner Criando Backlog

```
User: "Crie backlog para autenticação"
  ↓
Product-Owner.generate_epic("Authentication system")
  → test-mcp.create_test_plan()      [✓ Plano de testes]
  → test-mcp.generate_scenarios()    [✓ Cenários BDD]
  ↓ retorna: epic + test_plan + scenarios
  
Product-Owner.generate_feature_breakdown(epic)
  → qa-mcp.run_linter()              [✓ Valida padrões]
  → test-mcp.generate_scenarios()    [✓ Cenários por feature]
  ↓ retorna: features + validation + scenarios
  
Product-Owner.generate_user_stories(features)
  → qa-mcp.run_linter()              [✓ Valida clareza]
  → test-mcp.generate_scenarios()    [✓ Cenários por story]
  ↓ retorna: stories + validation + scenarios
  
Product-Owner.validate_story_readiness()
  → qa-mcp.run_linter()              [✓ Tudo claro?]
  → test-mcp.double_check()          [✓ Tudo pronto?]
  ↓ retorna: validation + qa_result + test_result
  
[Session finaliza]
  ↓
session-mcp.save_checkpoint()        [✓ Registra milestone]
deploy-mcp.commit_files()            [✓ Versiona uma única vez]
  ↓
✅ Backlog completo + validado + versionado
```

---

## Replicar para Outros DevTeam

### Architecture
- Chama `infra-mcp` para validar políticas de arquitetura
- Chama `ai-governance-mcp` para ADRs
- Chama `docs-mcp` para documentar decisões

### Backend
- Chama `qa-mcp` para testes de API
- Chama `test-mcp` para testes de banco
- Chama `docs-mcp` para contratos OpenAPI

### DevOps
- Chama `infra-mcp` para validação Terraform
- Chama `qa-mcp` para linting Docker/K8s
- Chama `deploy-mcp` para setup de pipelines

### Frontend + PixelFera
- Chama `qa-mcp` para accessibility checks
- Chama `test-mcp` para test generation
- Chama `docs-mcp` para storybook docs

### Product-Manager
- Chama `qa-mcp` para validation de roadmaps
- Chama `test-mcp` para discovery tests
- Chama `docs-mcp` para documentar PRDs

---

## Padrão de Dependências por DevTeam

| DevTeam | Chama | Propósito |
|-------|-------|-----------|
| **Product-Owner** | qa-mcp, test-mcp, docs-mcp, deploy-mcp | Backlog + validação + commit |
| **Architecture** | infra-mcp, ai-governance-mcp, docs-mcp | Arquitetura + políticas + docs |
| **Backend** | qa-mcp, test-mcp, deploy-mcp, docs-mcp | APIs + testes + deployment |
| **DevOps** | infra-mcp, qa-mcp, deploy-mcp | Infra + CI/CD |
| **Frontend** | qa-mcp, test-mcp, docs-mcp | UI + testes + storybook |
| **PixelFera** | qa-mcp, docs-mcp | Design tokens + validação |
| **Product-Manager** | qa-mcp, test-mcp, docs-mcp | Roadmap + discovery + PRDs |

---

## Package.json Template para DevTeam

```json
{
  "dependencies": {
    "@platform/mcp-client": "file:../shared",
    "@modelcontextprotocol/sdk": "^1.0.0",
    "zod": "^3.22.4",
    "better-sqlite3": "^9.0.0",
    "nanoid": "^4.0.2"
  }
}
```

---

## Próximos Passos

1. ✅ Product-Owner com integração (em andamento)
2. → Architecture com integração
3. → Backend com integração
4. → DevOps com integração
5. → Frontend + PixelFera com integração
6. → Product-Manager com integração
