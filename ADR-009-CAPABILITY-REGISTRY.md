# ADR-009 — Capability Registry (Platform Catalog · Fase 1)

**Status:** Proposed (V2) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-007 (capability model — resolve sua open question), ADR-008 (north-star registry — concretiza), ADR-005 (PDP consome), ADR-004 (risk→TTL), ADR-003 (workload identity), ADR-006 (session binding)
**Histórico:** V2 incorpora 2ª revisão de arquitetura — entidade **Operation** de 1ª classe, componente reposicionado como **Platform Catalog / Control Plane**, `provider` por referência, `effects` × `requires`, contrato com pré/pós-condições + perfil de execução, discovery API.

## Context

Hoje o `platform-dev` expõe **298 tools organizadas por MCP server** (`services-mcp`, `deploy-mcp`,
`qa-mcp`, …). Isso é a **implementação**, não o **domínio**. Consequências já visíveis:

1. **Acoplamento a provider.** Dividir `deploy-mcp` em `deploy`/`release`/`promotion` muda o catálogo
   inteiro, mesmo que a *capacidade* "deploy de serviço" não mude.
2. **Explosão de descoberta.** 298 tools hoje; 600–1200 em seis meses. Listar por server é inviável.
3. **Contrato espalhado.** O ADR-007 fixou o modelo de capability mas deixou a **open question**: *fonte da
   verdade do risk tier — código da tool ou registry?* Sem registry central, o PDP (ADR-005) não tem
   catálogo único, e não há versão/depreciação.
4. **Sem portabilidade (o gap novo).** Amanhã `deploy-mcp`, `argo`, `terraform` e um `github-action`
   implementarão a **mesma** operação "Deploy Service". Se a capability apontar direto pra tool/provider, o
   domínio fica acoplado à implementação e não há como trocar/multiplexar providers.

Já existe **fundação latente**: o `mcp-registry.py` (`:8000`) e o grafo de ecossistema do
`ai-governance-mcp` (`query_ecosystem_graph`, `get_service_metadata`, `find_dependencies_of`, …). Falta
**promovê-lo a fonte da verdade governada**. Isto **não é rewrite do runtime**
(`platform-dev-agent` — hoje repo standalone `platform-devs-agent`, pacote `app/devs_agent`: planner→approval→executor, DAGs, personas permanece) — é uma **camada de
catálogo/domínio** acima de providers que já funcionam.

## Decision

**D9.1 — Inversão do modelo (decisão central).** O `platform-dev` deixa de expor **tools por MCP provider**
e passa a expor **capabilities por domínio, recurso e operação**. Os MCP servers **continuam como providers
técnicos**, mas deixam de ser o modelo conceitual principal.

**D9.2 — O componente é um Platform Catalog (Control Plane), não só um registry.** O Capability Registry é
a **primeira faceta** de um catálogo maior. O schema e a API já nascem pensando nele; a Fase-1 popula só o
núcleo (Capabilities/Operations/Tools/Providers/Resources) — o resto entra no rollout:

```
Platform Catalog (Control Plane)
├── Capabilities   ┐
├── Operations     │  Fase 1 (este ADR)
├── Tools          │
├── Providers      │
├── Resources      ┘
├── Policies · Runbooks · Personas · Prompts · ADRs · Templates · Knowledge   (Fase 5 — Asset Catalog)
```

**D9.3 — Modelo de entidades (a hierarquia, com a Operation de 1ª classe):**

```
Domain  ⊃  Capability  ⊃  Operation  ──implementada por 1..N──▶  Tool  ──pertence a──▶  Provider
                              │
                              └── atua sobre ──▶ Resource
```

- **Operation** = o **contrato de domínio, provider-agnóstico** (a unidade estável de política e discovery).
- **Tool** = o **binding técnico** (a implementação concreta de uma Operation por um Provider).
- Uma Operation tem **N Tools** → portabilidade: `delivery.service.deploy` pode ser servida por `deploy-mcp`,
  `argo` ou `terraform` sem mudar o domínio nem os consumidores.

**D9.4 — Schema da Operation** (o contrato de domínio — id canônico, provider-agnóstico):

```yaml
id: delivery.service.deploy          # <domain>.<resource>.<operation> — estável, provider-agnóstico
domain: delivery                      # Architecture|Development|Testing|Delivery|Governance|Infra|Observability|Security|Documentation
capability: deployment                # agrupador dentro do domínio
resource:                             # sobre QUE recurso opera (D9.8)
  type: service
  parent: environment                 # preparado p/ hierarquia (Organization→Repo→Branch→PR / Env→Namespace→Deployment)
  namespace: null
operation: deploy                     # o verbo

authz:
  capability: write                   # read | write — o GATE de authz (ADR-007), deny-by-default

risk:                                 # descritor ORTOGONAL (D9.7)
  effects: [deploy, restart]          # o que a operação FAZ (deploy|delete|restart|shell|filesystem|financial|…)
  requires: [kubernetes, github, acr] # de que a operação DEPENDE (efeito ≠ dependência)
  blast_radius: environment           # none|workspace|service|environment|tenant|global
  default_level: high                 # low|medium|high|critical (tiers ADR-007 → TTL/HILT)
  approval_required: N2                # none|N1|N2 (HILT ADR-005)

contract:
  inputs: {}                          # JSON Schema
  outputs: {}                         # JSON Schema
  preconditions: []                   # ex.: "branch existe", "pipeline aprovado", "tenant válido"
  postconditions: []                  # ex.: "deployment ativo"
  execution:                          # perfil que o PLANNER lê (D9.8)
    idempotent: false                 # → resume_writes_safe do executor (ver nota)
    side_effects: true
    async: true
    streaming: false
    timeout_s: 900
    retry_policy: none                # none|read-only|backoff(n)

metadata:
  tags: [devops, release, production]
  owner: platform
  lifecycle: stable                   # experimental|stable|deprecated
  cost: medium
  latency: async
examples: []
```

**D9.5 — Schema do Tool binding** (a implementação; `provider` é uma **referência**, não embutido):

```yaml
operation_id: delivery.service.deploy
provider_id: deploy-mcp               # referência ao Provider (recurso próprio do catálogo)
provider_version: 1.0.0
tool: deploy                          # operationId concreto exposto pelo provider
endpoint: streamable-http             # transporte (ADR-006)
# selection: preference/weight/health — quando N tools implementam a mesma Operation (open question)
```

**D9.6 — Provider como recurso do catálogo** (`provider_id`, `kind`, `transport`, `version`, `owner`,
`health`) — evita duplicar dados do provider em cada tool e liga ao grafo de ecossistema do ai-governance.

**D9.7 — Registry = Source of Truth (resolve a open question do ADR-007).** `risk`, `authz`, `contract` e
`lifecycle` vivem **no catálogo**, não espalhados no código das tools. O `list_tools`/`capability_of` do
agente e o **PDP (ADR-005)** leem do catálogo. A tool no server continua declarando o contrato (ADR-007
D7.1) como *fonte de ingestão*; o **catálogo é a autoridade** consolidada, versionada e auditável.

**D9.8 — Risk ortogonal + contrato rico (refina ADR-007; separa efeito de dependência).** `authz.capability
= read|write` continua o gate simples (não fragmentar em N permissões). `risk.effects[]` (o que faz) +
`risk.requires[]` (do que depende) + `risk.blast_radius` são **ortogonais** e alimentam `default_level` +
`approval_required` — assim `deploy` ≠ `delete_production` **sem** inflar permissões (estilo OPA/Cedar). O
`contract.execution` (idempotent/side_effects/async/timeout/retry) é lido pelo **planner** para decisões
automáticas. **Nota — aterramento real:** o gateway `platform-mcp` **não deduplica writes por
`Idempotency-Key`** (verificado; só retenta reads), por isso o executor usa hoje `resume_writes_safe=False`.
Com `contract.execution.idempotent` no catálogo, o planner passa a decidir resume-safety **por metadata**,
não por heurística global.

**D9.9 — Discovery API (o catálogo é consultável, não só armazenado):**
`get(id)` · `search(q)` · `list_by_domain(d)` · `find_by_resource(r)` · `find_by_effect(e)` ·
`find_by_owner(o)` · `find_by_risk(level)` · `list_tools_for(operation_id)`.

**D9.10 — Migração aditiva e não-destrutiva.** Catálogo introduzido **por cima** dos providers (que não
mudam); **seed inicial gerado da auditoria dos 298 tools**; o agente lê o catálogo com *fallback* para o
`tools/list` do provider durante a transição; motor intacto. **O schema define o alvo; a Fase-1 popula o
núcleo** — campos avançados (`preconditions`, hierarquia de `resource`, `selection`) são opcionais e
preenchidos incrementalmente por curadoria.

## Consequences

- **+** Descoberta/UX por **domínio/capacidade**, não por 298+ funções; catálogo consultável (D9.9).
- **+** **Operation** desacopla domínio de implementação → múltiplos providers para a mesma operação sem
  quebrar consumidores (o gap #4).
- **+** Fonte única para **PDP, policy, discovery, auditoria e governança** (destrava as fases 2–6).
- **+** `contract.execution` torna o planner mais inteligente (idempotência, timeouts, async) — resolve
  resume-safety por metadata em vez de heurística.
- **+** Componente já nasce como **Control Plane**, não um registry que precisa ser renomeado depois.
- **−** **Curadoria** dos ~298 tools + modelagem de Operations/Resources (mitigado pelo seed automático;
  campos avançados incrementais).
- **−** Novo componente com estado (catálogo) a operar/versionar/monitorar.
- **−** Duplicação transitória (contrato na tool *e* no catálogo) até o catálogo ser 100% autoritativo.
- **−** A camada Operation↔Tool adiciona um nível de indireção (custo aceitável pela portabilidade).

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|---|---|
| **Organização por MCP server** | Acopla catálogo à implementação; descoberta não escala; sem versão/lifecycle/policy central. |
| **Capability → Tool direto (sem Operation)** | Acopla domínio à implementação; impossível ter N providers para a mesma operação (gap #4). |
| **Novo enum de permissões** (`EXECUTE/SHELL/DELETE/…`) | Fragmenta o authz (o que o ADR-007 evitou). `effects`+`requires`+`blast_radius` ortogonais dão a precisão sem a explosão. |
| **`provider` embutido em cada tool** | Duplica dados do provider; Provider como recurso referenciado normaliza. |
| **Começar por Events/runbooks** | Não destravam discovery/policy; dependem do catálogo (pré-requisito). |
| **Registry só em memória no agente** | Sem versão/auditoria/consumo pelo PDP; não é *source of truth* governada. |

## Rollout (prioridade — este ADR é a Fase 1)

```
1. Platform Catalog + Capability/Operation/Tool/Provider/Resource   ← ESTE ADR
2. Resource + Effect Model como enforcement no PDP
3. Policy/Risk Engine por metadata
4. Events no Kafka (dataforall-kafka já existe)
5. Asset Catalog (Policies/Runbooks/Personas/Prompts/ADRs/Templates/Knowledge no mesmo catálogo)
6. Expansão dos runbooks
```

## Open questions

- **Seleção de Tool** quando N implementam a mesma Operation: por `preference`/`cost`/`latency`/`health`?
- **Ownership de domínio:** dono de cada namespace (`delivery`, `security`, `testing`, …)?
- **Persistência:** declarativo em git (GitOps) × Postgres governado × híbrido.
- **Ingestão:** catálogo *puxa* (scan do `tools/list`) × tools *empurram* no startup?
- **Migração do `SCOPE_FOR_TOOL`:** `required_scope` por-tool vira derivado do catálogo ou cache local?
- **Fronteira do Catalog × ai-governance ecosystem graph:** quem é dono do resource/dependency graph?

## References

- ADR-007 (Capability Model) — contrato per-tool que este ADR consolida no catálogo
- ADR-008 (North-Star) — registry north-star, aqui concretizado como Platform Catalog
- ADR-005 (PEP/PDP) — consumidor primário · ADR-004 (risk→TTL) · ADR-006 (transporte no Tool binding)
- `mcp-registry.py` (`:8000`) — base a promover · auditoria dos 298 tools (seed) · ai-governance ecosystem graph (resources)
- Prior-art: Backstage (software catalog), OPA/Cedar (policy-as-attributes), CloudEvents (fase 4), Crossplane/K8s (resource model + hierarquia)
