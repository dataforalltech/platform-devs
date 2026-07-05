# DevTeam Integration Examples — Phase 1-4 MCPs

## Overview
Cada um dos 8 DevTeam deve usar a classe `DevTeamIntegration` para coordenar com os MCPs:
1. **knowledge-base-mcp** — Contexto de documentação
2. **cross-devteam-validators** — Validação de handoffs
3. **quality-gates-system** — Gates de qualidade
4. **devteam-observatory** — Métricas em tempo real

---

## Integration Pattern

```typescript
import DevTeamIntegration from '../DevTeamIntegration';

const devteamInt = new DevTeamIntegration('YourDevTeamName');

const result = await devteamInt.executeWorkflow(
  'task_name',
  async () => {
    // Sua ação aqui
    return { success: true };
  },
  [
    { from: 'Product-Manager', to: 'Architecture', payload: {...} },
    { from: 'Architecture', to: 'Backend', payload: {...} },
  ]
);
```

---

## 1. Product-Manager Integration

**Função:** Define specs de features, cria epics, stories
**Integração:**
- Chamar `knowledge-base-mcp.search_governance_knowledge` para contexto de projeto
- Validar spec com `cross-devteam-validators.validate_completeness`
- Registrar spec criada no `devteam-observatory`

**Exemplo:**

```typescript
async generateFeatureSpec(requirement: string) {
  const devteamInt = new DevTeamIntegration('Product-Manager');
  
  return devteamInt.executeWorkflow(
    'generate_feature_spec',
    async () => {
      const spec = await this.generateSpec(requirement);
      return { spec_id: spec.id, title: spec.title };
    },
    [] // Sem dependências externas no início
  );
}

async handoffToArchitecture(specId: string, spec: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('Product-Manager');
  
  await devteamInt.validateHandoff(
    'Product-Manager',
    'Architecture',
    { spec_id: specId, spec }
  );
}
```

---

## 2. Architecture Integration

**Função:** Desenha arquitetura, define modules, bounded contexts
**Integração:**
- Ler spec de Product-Manager via `knowledge-base-mcp`
- Validar com `cross-devteam-validators` antes de handoff
- Registrar blueprint no `devteam-observatory`

**Exemplo:**

```typescript
async designArchitecture(specId: string, requirement: string) {
  const devteamInt = new DevTeamIntegration('Architecture');
  
  return devteamInt.executeWorkflow(
    `design_architecture_${specId}`,
    async () => {
      const blueprint = await this.generateBlueprint(requirement);
      return { blueprint_id: blueprint.id, style: blueprint.style };
    },
    [{ from: 'Product-Manager', to: 'Architecture', payload: { spec_id: specId } }]
  );
}

async handoffToBackend(blueprintId: string, blueprint: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('Architecture');
  
  await devteamInt.validateHandoff(
    'Architecture',
    'Backend',
    { blueprint_id: blueprintId, blueprint }
  );
}
```

---

## 3. Backend Integration

**Função:** Implementa APIs, databases, serviços
**Integração:**
- Ler blueprint de Architecture
- Validar com `cross-devteam-validators`
- Executar `quality-gates-system` para code quality
- Registrar progresso no `devteam-observatory`

**Exemplo:**

```typescript
async implementAPI(blueprintId: string, blueprint: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('Backend');
  
  return devteamInt.executeWorkflow(
    `implement_api_${blueprintId}`,
    async () => {
      const api = await this.generateAPI(blueprint);
      return { api_id: api.id, endpoints: api.endpoint_count };
    },
    [{ from: 'Architecture', to: 'Backend', payload: { blueprint_id: blueprintId } }]
  );
}
```

---

## 4. Frontend-PixelFera Integration

**Função:** Desenha UI, cria components
**Integração:**
- Ler spec de Product-Manager
- Validar acessibilidade com `quality-gates-system.accessibility_gate`
- Registrar design progress no `devteam-observatory`

**Exemplo:**

```typescript
async designUI(specId: string, spec: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('Frontend');
  
  return devteamInt.executeWorkflow(
    `design_ui_${specId}`,
    async () => {
      const design = await this.generateDesign(spec);
      return { design_id: design.id, components: design.component_count };
    },
    [{ from: 'Product-Manager', to: 'Frontend', payload: { spec_id: specId } }]
  );
}
```

---

## 5. DevOps Integration

**Função:** Deployment, infrastructure, observability
**Integração:**
- Ler blueprint de Architecture
- Validar performance gates com `quality-gates-system`
- Registrar deployment metrics no `devteam-observatory`

**Exemplo:**

```typescript
async deployService(apiId: string, api: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('DevOps');
  
  return devteamInt.executeWorkflow(
    `deploy_${apiId}`,
    async () => {
      const deployment = await this.deploy(api);
      return { deployment_id: deployment.id, status: 'deployed' };
    },
    [{ from: 'Backend', to: 'DevOps', payload: { api_id: apiId } }]
  );
}
```

---

## 6. QA-Engineer Integration

**Função:** Testa E2E, valida cobertura, security tests
**Integração:**
- Ler spec de Product-Manager
- Executar `quality-gates-system.test_coverage_gate`
- Registrar resultados de teste no `devteam-observatory`

**Exemplo:**

```typescript
async runE2ETests(specId: string, spec: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('QA-Engineer');
  
  return devteamInt.executeWorkflow(
    `e2e_tests_${specId}`,
    async () => {
      const results = await this.runTests(spec);
      return { passed: results.passed, coverage: results.coverage };
    },
    [
      { from: 'Frontend', to: 'QA-Engineer', payload: { design_id: '' } },
      { from: 'Backend', to: 'QA-Engineer', payload: { api_id: '' } }
    ]
  );
}
```

---

## 7. Security Integration

**Função:** Threat modeling, security review, compliance
**Integração:**
- Ler blueprint e API de Architecture/Backend
- Executar `quality-gates-system.security_review_gate`
- Registrar security findings no `devteam-observatory`

**Exemplo:**

```typescript
async threatModel(blueprintId: string, blueprint: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('Security');
  
  return devteamInt.executeWorkflow(
    `threat_model_${blueprintId}`,
    async () => {
      const threats = await this.generateThreatModel(blueprint);
      return { threats_count: threats.length, severity: threats[0]?.severity };
    },
    [{ from: 'Architecture', to: 'Security', payload: { blueprint_id: blueprintId } }]
  );
}
```

---

## 8. Product-Owner Integration

**Função:** Prioriza backlog, quebra em tasks, coordena timeline
**Integração:**
- Ler spec de Product-Manager
- Orquestrar validações de handoff
- Registrar progress de todo o pipeline no `devteam-observatory`

**Exemplo:**

```typescript
async breakdownFeatureIntoStories(specId: string, spec: Record<string, unknown>) {
  const devteamInt = new DevTeamIntegration('Product-Owner');
  
  return devteamInt.executeWorkflow(
    `breakdown_${specId}`,
    async () => {
      const stories = await this.breakdown(spec);
      return { stories_count: stories.length, total_points: stories.reduce((s, st) => s + st.points, 0) };
    },
    [{ from: 'Product-Manager', to: 'Product-Owner', payload: { spec_id: specId } }]
  );
}
```

---

## Full Feature Flow — E2E Example

```
Product-Manager.generateFeatureSpec('OAuth2 Integration')
  ↓ [validate_completeness] ✅
  → Architecture.designArchitecture(spec)
  ↓ [validate_schema_compliance] ✅
  → Backend.implementAPI(blueprint)
  ↓ [code_quality_gate] ✅
  → Frontend.designUI(spec)
  ↓ [accessibility_gate] ✅
  → DevOps.deployService(api)
  ↓ [performance_gate] ✅
  → QA-Engineer.runE2ETests(spec)
  ↓ [test_coverage_gate] ✅
  → Security.threatModel(blueprint)
  ↓ [security_review_gate] ✅
  → Product-Owner.assignToTeam(stories)
  
RESULT: Observatory mostra progresso completo ✅ ALL GATES PASSED
```

---

## Deployment Instructions

1. **Copy DevTeamIntegration.ts** para raiz do repositório
2. **Adicione import em cada DevTeam server:**
   ```typescript
   import DevTeamIntegration from '../../DevTeamIntegration';
   ```
3. **Wrap executores principais com `executeWorkflow()`**
4. **Deploy e teste com feature E2E OAuth2**

---

## Status

- PASSO 1: ✅ 4 PRs Criadas
- PASSO 2: ⏳ Integração com 8 DevTeam (padrão acima)
- PASSO 3: ⏳ Teste E2E OAuth2
- PASSO 4: ⏳ Deploy para produção
