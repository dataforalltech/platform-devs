# Zilla Integration Examples — Phase 1-4 MCPs

## Overview
Cada um dos 8 Zillas deve usar a classe `ZillaIntegration` para coordenar com os MCPs:
1. **knowledge-base-mcp** — Contexto de documentação
2. **cross-zilla-validators** — Validação de handoffs
3. **quality-gates-system** — Gates de qualidade
4. **zilla-observatory** — Métricas em tempo real

---

## Integration Pattern

```typescript
import ZillaIntegration from '../ZillaIntegration';

const zillaInt = new ZillaIntegration('YourZillaName');

const result = await zillaInt.executeWorkflow(
  'task_name',
  async () => {
    // Sua ação aqui
    return { success: true };
  },
  [
    { from: 'ProductZilla', to: 'ArchZilla', payload: {...} },
    { from: 'ArchZilla', to: 'BackZilla', payload: {...} },
  ]
);
```

---

## 1. ProductZilla Integration

**Função:** Define specs de features, cria epics, stories
**Integração:**
- Chamar `knowledge-base-mcp.search_governance_knowledge` para contexto de projeto
- Validar spec com `cross-zilla-validators.validate_completeness`
- Registrar spec criada no `zilla-observatory`

**Exemplo:**

```typescript
async generateFeatureSpec(requirement: string) {
  const zillaInt = new ZillaIntegration('ProductZilla');
  
  return zillaInt.executeWorkflow(
    'generate_feature_spec',
    async () => {
      const spec = await this.generateSpec(requirement);
      return { spec_id: spec.id, title: spec.title };
    },
    [] // Sem dependências externas no início
  );
}

async handoffToArchZilla(specId: string, spec: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('ProductZilla');
  
  await zillaInt.validateHandoff(
    'ProductZilla',
    'ArchZilla',
    { spec_id: specId, spec }
  );
}
```

---

## 2. ArchZilla Integration

**Função:** Desenha arquitetura, define modules, bounded contexts
**Integração:**
- Ler spec de ProductZilla via `knowledge-base-mcp`
- Validar com `cross-zilla-validators` antes de handoff
- Registrar blueprint no `zilla-observatory`

**Exemplo:**

```typescript
async designArchitecture(specId: string, requirement: string) {
  const zillaInt = new ZillaIntegration('ArchZilla');
  
  return zillaInt.executeWorkflow(
    `design_architecture_${specId}`,
    async () => {
      const blueprint = await this.generateBlueprint(requirement);
      return { blueprint_id: blueprint.id, style: blueprint.style };
    },
    [{ from: 'ProductZilla', to: 'ArchZilla', payload: { spec_id: specId } }]
  );
}

async handoffToBackZilla(blueprintId: string, blueprint: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('ArchZilla');
  
  await zillaInt.validateHandoff(
    'ArchZilla',
    'BackZilla',
    { blueprint_id: blueprintId, blueprint }
  );
}
```

---

## 3. BackZilla Integration

**Função:** Implementa APIs, databases, serviços
**Integração:**
- Ler blueprint de ArchZilla
- Validar com `cross-zilla-validators`
- Executar `quality-gates-system` para code quality
- Registrar progresso no `zilla-observatory`

**Exemplo:**

```typescript
async implementAPI(blueprintId: string, blueprint: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('BackZilla');
  
  return zillaInt.executeWorkflow(
    `implement_api_${blueprintId}`,
    async () => {
      const api = await this.generateAPI(blueprint);
      return { api_id: api.id, endpoints: api.endpoint_count };
    },
    [{ from: 'ArchZilla', to: 'BackZilla', payload: { blueprint_id: blueprintId } }]
  );
}
```

---

## 4. FrontZilla-PixelFera Integration

**Função:** Desenha UI, cria components
**Integração:**
- Ler spec de ProductZilla
- Validar acessibilidade com `quality-gates-system.accessibility_gate`
- Registrar design progress no `zilla-observatory`

**Exemplo:**

```typescript
async designUI(specId: string, spec: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('FrontZilla');
  
  return zillaInt.executeWorkflow(
    `design_ui_${specId}`,
    async () => {
      const design = await this.generateDesign(spec);
      return { design_id: design.id, components: design.component_count };
    },
    [{ from: 'ProductZilla', to: 'FrontZilla', payload: { spec_id: specId } }]
  );
}
```

---

## 5. OpsZilla Integration

**Função:** Deployment, infrastructure, observability
**Integração:**
- Ler blueprint de ArchZilla
- Validar performance gates com `quality-gates-system`
- Registrar deployment metrics no `zilla-observatory`

**Exemplo:**

```typescript
async deployService(apiId: string, api: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('OpsZilla');
  
  return zillaInt.executeWorkflow(
    `deploy_${apiId}`,
    async () => {
      const deployment = await this.deploy(api);
      return { deployment_id: deployment.id, status: 'deployed' };
    },
    [{ from: 'BackZilla', to: 'OpsZilla', payload: { api_id: apiId } }]
  );
}
```

---

## 6. QAZilla Integration

**Função:** Testa E2E, valida cobertura, security tests
**Integração:**
- Ler spec de ProductZilla
- Executar `quality-gates-system.test_coverage_gate`
- Registrar resultados de teste no `zilla-observatory`

**Exemplo:**

```typescript
async runE2ETests(specId: string, spec: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('QAZilla');
  
  return zillaInt.executeWorkflow(
    `e2e_tests_${specId}`,
    async () => {
      const results = await this.runTests(spec);
      return { passed: results.passed, coverage: results.coverage };
    },
    [
      { from: 'FrontZilla', to: 'QAZilla', payload: { design_id: '' } },
      { from: 'BackZilla', to: 'QAZilla', payload: { api_id: '' } }
    ]
  );
}
```

---

## 7. SecZilla Integration

**Função:** Threat modeling, security review, compliance
**Integração:**
- Ler blueprint e API de ArchZilla/BackZilla
- Executar `quality-gates-system.security_review_gate`
- Registrar security findings no `zilla-observatory`

**Exemplo:**

```typescript
async threatModel(blueprintId: string, blueprint: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('SecZilla');
  
  return zillaInt.executeWorkflow(
    `threat_model_${blueprintId}`,
    async () => {
      const threats = await this.generateThreatModel(blueprint);
      return { threats_count: threats.length, severity: threats[0]?.severity };
    },
    [{ from: 'ArchZilla', to: 'SecZilla', payload: { blueprint_id: blueprintId } }]
  );
}
```

---

## 8. POZilla Integration

**Função:** Prioriza backlog, quebra em tasks, coordena timeline
**Integração:**
- Ler spec de ProductZilla
- Orquestrar validações de handoff
- Registrar progress de todo o pipeline no `zilla-observatory`

**Exemplo:**

```typescript
async breakdownFeatureIntoStories(specId: string, spec: Record<string, unknown>) {
  const zillaInt = new ZillaIntegration('POZilla');
  
  return zillaInt.executeWorkflow(
    `breakdown_${specId}`,
    async () => {
      const stories = await this.breakdown(spec);
      return { stories_count: stories.length, total_points: stories.reduce((s, st) => s + st.points, 0) };
    },
    [{ from: 'ProductZilla', to: 'POZilla', payload: { spec_id: specId } }]
  );
}
```

---

## Full Feature Flow — E2E Example

```
ProductZilla.generateFeatureSpec('OAuth2 Integration')
  ↓ [validate_completeness] ✅
  → ArchZilla.designArchitecture(spec)
  ↓ [validate_schema_compliance] ✅
  → BackZilla.implementAPI(blueprint)
  ↓ [code_quality_gate] ✅
  → FrontZilla.designUI(spec)
  ↓ [accessibility_gate] ✅
  → OpsZilla.deployService(api)
  ↓ [performance_gate] ✅
  → QAZilla.runE2ETests(spec)
  ↓ [test_coverage_gate] ✅
  → SecZilla.threatModel(blueprint)
  ↓ [security_review_gate] ✅
  → POZilla.assignToTeam(stories)
  
RESULT: Observatory mostra progresso completo ✅ ALL GATES PASSED
```

---

## Deployment Instructions

1. **Copy ZillaIntegration.ts** para raiz do repositório
2. **Adicione import em cada Zilla server:**
   ```typescript
   import ZillaIntegration from '../../ZillaIntegration';
   ```
3. **Wrap executores principais com `executeWorkflow()`**
4. **Deploy e teste com feature E2E OAuth2**

---

## Status

- PASSO 1: ✅ 4 PRs Criadas
- PASSO 2: ⏳ Integração com 8 Zillas (padrão acima)
- PASSO 3: ⏳ Teste E2E OAuth2
- PASSO 4: ⏳ Deploy para produção
