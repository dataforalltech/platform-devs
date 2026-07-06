# ADR-010 — Platform Catalog — Meta-modelo de Kinds

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-009 (entrega o núcleo Capability/Operation/Tool/Provider/Resource — o **primeiro kind já especificado**), ADR-011 (Discovery consome este meta-modelo), ADR-014 (instâncias de asset), ADR-012 (Event Model), ADR-007 (Capability Model), ADR-005 (PDP consome)

## Context

A ADR-009 inverteu o modelo do `platform-dev` (de *tools por provider* para *capabilities por domínio*) e
especificou **cinco entidades** — Capability, Operation, Tool, Provider, Resource — com seus campos de `spec`
(`authz`, `risk`, `contract`, `provider binding`, …). Mas a ADR-009 também declarou que isso é a **Fase 1** de
um **Platform Catalog / Control Plane** que crescerá para incluir Policies, Runbooks, Personas, Prompts,
Templates e Knowledge (Fase 5 — Asset Catalog).

Sem um **meta-modelo comum**, cada nova entidade reinventaria seu envelope, sua identidade, suas relações e
seu versionamento — exatamente o acoplamento que a ADR-009 combateu, só que um nível acima. Consequências já
previsíveis:

1. **Envelopes divergentes.** Operation tem `metadata.owner/lifecycle/tags`; um Runbook inventaria os seus
   próprios campos. Discovery (ADR-011) teria de conhecer N formatos. Sem envelope comum, não há query
   uniforme (`find_by_owner`, `find_by_lifecycle`, `find_by_tag`) atravessando kinds.
2. **Relações ad-hoc.** A ADR-009 já expressa `Operation ──implementada por──▶ Tool ──pertence a──▶ Provider`
   e `Operation ──atua sobre──▶ Resource`. Um Runbook *usa* Operations; uma Persona *é dona de* um domínio;
   uma Policy *governa* Operations. Sem um **grafo de relações tipado e comum**, cada aresta vira campo
   arbitrário e o grafo não é navegável de forma genérica.
3. **Identidade inconsistente.** Operation tem id canônico `<domain>.<resource>.<operation>` (ADR-009 D9.4).
   Provider tem `provider_id`. Falta a **regra geral**: o que é `kind`, o que é `name`, o que é o id global e
   único que o Discovery e o PDP referenciam através de kinds.
4. **Versionamento do schema não definido.** A ADR-009 tem `lifecycle` da *entidade* (experimental/stable/
   deprecated), mas não o versionamento do *próprio formato* — como evoluir o envelope sem quebrar consumidores.

Prior-art direto: o **Software Catalog do Backstage** resolve isto com um envelope único
(`apiVersion`/`kind`/`metadata`/`spec`/`relations`) e um conjunto fechado de kinds (Component/API/Resource/
System/…) ligados por relações tipadas. Adotamos a **forma**, com os **kinds do nosso domínio** — os cinco da
ADR-009 já existentes, mais os kinds de asset da Fase 5. Este ADR **não redefine os `spec`** dos kinds da
ADR-009 (referencia-os) e **não define** a API de Discovery (ADR-011), os `spec` detalhados dos assets
(ADR-014) nem os eventos (ADR-012).

## Decision

**D10.1 — Envelope comum de toda entidade do catálogo.** Toda entrada, independentemente do `kind`, tem a
mesma estrutura de topo. É isto que torna o catálogo consultável de forma uniforme e o Discovery (ADR-011)
agnóstico a kind.

```yaml
apiVersion: catalog.platform/v1        # versão do META-MODELO (D10.9), não da entidade
kind: Operation                        # um dos kinds oficiais (D10.3)
metadata:
  name: service.deploy                 # nome legível, único dentro do (kind, namespace) — D10.6
  uid: op_01J...                        # id opaco imutável gerado no ingest (nunca reusado) — D10.6
  namespace: delivery                  # partição lógica; default para o domain no caso de Operation
  title: Deploy Service                # rótulo humano opcional para UX/Discovery
  description: ""                       # texto livre opcional
  owner: platform                      # dono (time/persona) — comum a TODOS os kinds
  tags: [devops, release]              # comum a todos — habilita find_by_tag cross-kind
  lifecycle: stable                    # experimental|stable|deprecated|retired — da ENTIDADE (não do schema)
  version: 2.1.0                       # SemVer da ENTIDADE (contrato/asset) — D10.9; ≠ apiVersion, ≠ resourceVersion
  annotations: {}                      # metadata de máquina (ex.: source do ingest, git sha, provider health)
  labels: {}                           # metadata de seleção (chave→valor curto), estilo K8s
spec: { ... }                          # PAYLOAD específico do kind — NÃO definido aqui p/ os kinds da ADR-009
relations: [ ... ]                     # arestas tipadas do grafo (D10.4)
resourceVersion: "..."                 # etag opaca de concorrência otimista — D10.9; ≠ metadata.version
```

**Contrato de fronteira (ADR-009):** o bloco `spec` de `Operation`/`Tool`/`Provider`/`Resource`/`Capability`
**é o que a ADR-009 D9.4–D9.6 define** (`authz`, `risk`, `contract`, `provider binding`, …). Este ADR só
padroniza o **envelope ao redor** do `spec` e a **compatibilidade de nomes**: os campos que a ADR-009 chamou
`metadata.owner/lifecycle/tags/cost/latency` são exatamente `metadata.owner/lifecycle/tags` do envelope
(+ `spec.cost`/`spec.latency` ficam no spec, pois são específicos de Operation). O id canônico
`<domain>.<resource>.<operation>` da ADR-009 é o **`name` qualificado** de uma Operation (D10.6), não um
campo à parte.

**D10.2 — `spec` é fechado por kind; envelope é aberto por annotation.** O `spec` só pode conter os campos que
o schema daquele kind declara (validação estrita — rejeita desconhecidos, alinhado ao *deny-by-default* do
authz). Extensões vão em `metadata.annotations`/`metadata.labels`, nunca em `spec`. Isso mantém o `spec` como
contrato governado e o envelope como zona de metadata evolutiva.

**D10.3 — Conjunto oficial de Kinds (fechado; extensível só por este ADR).** Duas famílias, um único envelope:

| Família | Kind | Papel | Spec definido por |
|---|---|---|---|
| **Core** (Fase 1) | `Capability` | agrupador de Operations dentro de um domínio | ADR-009 |
| | `Operation` | contrato de domínio provider-agnóstico (unidade de política/discovery) | ADR-009 D9.4 |
| | `Tool` | binding técnico (provider_id + version + operationId) | ADR-009 D9.5 |
| | `Provider` | recurso que expõe Tools (MCP server) | ADR-009 D9.6 |
| | `Resource` | sobre o que uma Operation atua (service, repo, env, …) | ADR-009 D9.4 (`resource`) |
| **Asset** (Fase 5) | `Runbook` | playbook multi-operação | ADR-014 |
| | `Persona` | perfil/agente com escopo e ownership | ADR-014 |
| | `Policy` | regra de governança (risk/purpose/mandate) | ADR-014 |
| | `Prompt` | prompt versionado | ADR-014 |
| | `Template` | scaffold/gerador | ADR-014 |
| | `Knowledge` | documento/ADR/nota de conhecimento | ADR-014 |

- Este ADR **owns o registro dos kinds e o envelope**. O `spec` de cada kind é **owned por outra ADR**
  (Core → ADR-009; Asset → ADR-014). Adicionar/remover um kind exige um ADR (não é config).
- `Domain` **não é um kind**: é uma **dimensão de namespace/ownership** (D10.6), não uma entidade com `spec`.
  Os domínios são o enum da ADR-009 D9.4 (`Architecture|Development|Testing|Delivery|Governance|Infra|
  Observability|Security|Documentation`).

**D10.4 — Modelo de Relations (grafo tipado, comum a todos os kinds).** Toda aresta é uma tripla
`(from → verb → to)` onde os nós são `uid`/`name qualificado` de entidades do catálogo. Verbos Core
(conjunto fechado):

```yaml
relations:
  - type: implements     # Tool     → Operation           (a ADR-009 "implementada por 1..N Tools")
  - type: provided-by    # Tool     → Provider             (a ADR-009 "pertence a Provider")
  - type: acts-on        # Operation→ Resource             (a ADR-009 "atua sobre Resource")
  - type: part-of        # Operation→ Capability; Resource → Resource(parent) (hierarquia D9.4)
  - type: depends-on     # qualquer → qualquer             (dependência lógica; ex.: Operation→Provider capability)
```

**Verbos de relation de asset** (registrados aqui; spec detalhado na ADR-014):

```yaml
relations:
  - type: owns           # Persona  → Domain/Capability/Operation (ownership de asset)
  - type: uses           # Persona  → Prompt; Runbook → Operation (composição de asset)
  - type: governs        # Policy   → Resource/effect/Capability   (escopo da política)
  - type: executes       # Runbook  → Operation                    (cada passo do DAG)
  - type: runAs          # Runbook  → Persona                      (perfil que executa)
  - type: allows         # Persona  → Capability/Operation         (allow-list)
  - type: supersedes     # qualquer → qualquer (mesmo kind)        (substituição em sunset)
  - type: derivedFrom    # Template → Operation/Knowledge          (o que o scaffold aplica)
  - type: sources        # qualquer → Knowledge                    (fonte de contexto/RAG)
  - type: decides        # ADR      → Capability/Operation         (memória arquitetural)
```

| Verbo | Direção canônica | Inverso implícito (derivado pelo Discovery) | Origem |
|---|---|---|---|
| `implements` | Tool → Operation | `implemented-by` | ADR-009 D9.3/D9.5 |
| `provided-by` | Tool → Provider | `provides` | ADR-009 D9.6 |
| `acts-on` | Operation → Resource | `acted-on-by` | ADR-009 D9.4 |
| `part-of` | filho → pai | `has-part` | ADR-009 (`capability`, `resource.parent`) |
| `depends-on` | dependente → dependência | `depended-on-by` | novo (genérico) |
| `owns` | Persona → alvo | `owned-by` | asset (semântica ADR-014) |
| `uses` | asset → alvo | `used-by` | asset (semântica ADR-014) |
| `governs` | Policy → alvo | `governed-by` | asset (semântica ADR-014) |
| `executes` | Runbook → Operation | `executed-by` | asset (semântica ADR-014) |
| `runAs` | Runbook → Persona | `runs` | asset (semântica ADR-014) |
| `allows` | Persona → alvo | `allowed-by` | asset (semântica ADR-014) |
| `supersedes` | novo → antigo | `superseded-by` | asset (semântica ADR-014) |
| `derivedFrom` | Template → alvo | `derives` | asset (semântica ADR-014) |
| `sources` | asset → Knowledge | `sourced-by` | asset (semântica ADR-014) |
| `decides` | ADR → alvo | `decided-by` | asset (semântica ADR-014) |

Regras: (a) o **registro de verbos é fechado e vive nesta ADR** — novos verbos exigem atualizar esta ADR (não
config/runtime); os verbos de asset já estão **registrados acima** e têm sua **semântica especificada pela
ADR-014** (esta ADR não delega o registro, só a semântica). (b) relações são **direcionais**, o inverso é
**derivado** pelo Discovery (não duplicado à mão); (c) a aresta **materializa** o que hoje já está implícito
nos campos de `spec` da ADR-009 (`operation_id`, `provider_id`, `resource.parent`, `capability`) — o ingest
projeta esses campos em `relations` para dar um **grafo navegável único** (o consumo/consulta é ADR-011).
Assets declaram os verbos de asset **diretamente**; seus `spec` são ADR-014.

**D10.5 — Referências entre entidades (target ref).** Um alvo de relação (ou uma referência dentro de um
`spec`, como `operation_id` da ADR-009) é resolvido por **`name` qualificado** (estável, legível) e opcionalmente
por **`uid`** (imutável). Forma canônica do ref:

```
[<kind>:][<namespace>/]<name>        # ex.: Operation:delivery/service.deploy  |  Provider:deploy-mcp
```

- `kind` e `namespace` são inferidos por contexto quando não ambíguos (ex.: `implements` sempre aponta a uma
  Operation). Ref **não resolvido** → entidade em estado `dangling` (o Discovery reporta; não quebra o ingest).

**D10.6 — Identidade e naming (a regra geral que a ADR-009 particularizou).**

| Conceito | Regra |
|---|---|
| **`uid`** | Id **opaco, imutável, global**, gerado no ingest (`<kindprefix>_<ULID>`). Nunca reusado, mesmo após `retired`. É o alvo estável de auditoria (ADR-012) e do PDP. |
| **`name`** | Legível e **único dentro de `(kind, namespace)`**. Slug `^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$`. |
| **`namespace`** | Partição lógica. Para kinds Core cujo domínio existe (Operation/Capability), `namespace == domain` (ADR-009 D9.4). Para Provider/Tool, namespace default `providers`. Para assets, o domínio dono. |
| **Nome qualificado** | `<namespace>/<name>`. Para **Operation**, isto é exatamente o id canônico `<domain>.<resource>.<operation>` da ADR-009 — ex.: namespace `delivery` + name `service.deploy` ⇒ `delivery.service.deploy`. **A ADR-009 é a especialização deste ADR para Operation.** |
| **Ref global** | `<kind>:<namespace>/<name>` (D10.5) — desambigua entre kinds. |
| **Unicidade** | `uid` é único globalmente; `(kind, namespace, name)` é único. Dois kinds **podem** compartilhar um `name` (ex.: `Runbook:delivery/deploy-canary` × `Operation:delivery/service.deploy`) — o `kind` desambigua. |

**D10.7 — Lifecycle da entidade × estado no catálogo (separados).** `metadata.lifecycle` é a **intenção de
maturidade** curada (`experimental|stable|deprecated|retired`). Isso é ortogonal a estados **operacionais**
derivados que o Discovery calcula (ex.: `dangling` por ref não resolvido, `unhealthy` por provider fora do ar
— ADR-011) e ao `spec.metadata.lifecycle` das Operations da ADR-009 (que é o **mesmo** campo, agora no
envelope — não duplicar). Regra: `retired` **não** apaga o `uid` (auditoria histórica); some do Discovery
default mas continua resolvível por `uid`.

**D10.8 — Kinds Core são *projeção*, não reescrita.** As cinco entidades da ADR-009 **não mudam de formato**:
o ingest (ADR-009 D9.10, seed dos 298 tools) passa a **embrulhá-las** no envelope D10.1 e a **projetar** suas
referências de `spec` em `relations` (D10.4). Nenhum campo de `spec` da ADR-009 é redefinido, renomeado ou
removido aqui. O envelope é aditivo — casa com a migração aditiva e não-destrutiva da ADR-009 D9.10.

**D10.9 — Três eixos de versão, independentes.** O catálogo separa explicitamente três versões que **não** se
confundem — cada uma respondendo a uma pergunta diferente:

| Eixo | Campo | O que versiona | Vive / consumida por |
|---|---|---|---|
| **Schema / meta-modelo** | `apiVersion` (`catalog.platform/v<major>`) | o **formato do envelope** (D10.1) | esta ADR; Discovery negocia (dual-read no breaking) |
| **Entidade (SemVer)** | `metadata.version` | o **contrato/asset em si** (a Operation, o Runbook, …) | **vive aqui**; consumida por ADR-011 (SemVer da Operation, D11.3) e ADR-014 (SemVer do asset, D14.4) |
| **Concorrência** | `resourceVersion`/etag | uma **revisão física opaca** (optimistic concurrency no ingest) | esta ADR; feed de mudança é ADR-012, discovery é ADR-011 |

O `metadata.version` é **SemVer da ENTIDADE** — ortogonal ao `apiVersion` (o esquema pode ser `v1` enquanto a
entidade está em `2.1.0`) e ao `provider_version` do Tool (ADR-009 D9.5), que é o binding técnico. Regras de
evolução do **`apiVersion`** (o esquema):

- **Aditivo (campo opcional novo, kind novo, verbo… não)** → mesma major (`v1`). Consumidores ignoram o que
  não conhecem (envelope aberto por annotation, D10.2).
- **Breaking (remover/renomear campo do envelope, mudar semântica de relação, remover kind/verbo)** → nova
  major (`v2`), com janela de **dual-read** (catálogo serve `v1` e `v2` durante a migração; ADR-011 negocia).
- **Enum de kinds e verbos** (D10.3/D10.4) só muda por ADR — nunca por config/runtime.
- A **`resourceVersion`/etag** (terceiro eixo acima) é a concorrência otimista no ingest; a **semântica de
  mudança e o feed** disso é ADR-012 (eventos) / ADR-011 (discovery), não este ADR. O **estado operacional**
  da entidade **não** é um campo de topo do envelope — permanece **derivado** pelo Discovery (D10.7).

## Consequences

- **+** Um **único envelope** ⇒ Discovery (ADR-011), PDP (ADR-005) e auditoria (ADR-012) tratam todo kind de
  forma uniforme (`find_by_owner`/`by_tag`/`by_lifecycle` atravessam kinds sem código por-entidade).
- **+** **Grafo tipado comum** materializa o que a ADR-009 tinha implícito em campos de `spec` e prepara os
  verbos de asset (`owns`/`uses`/`governs`/`executes`/`runAs`/… — registro completo em D10.4) — o catálogo
  vira grafo navegável, não tabelas isoladas.
- **+** **Identidade uniforme** (`uid` imutável + `name` qualificado) resolve a inconsistência id-canônico ×
  `provider_id`, dá alvo estável para auditoria/PDP e mostra a ADR-009 como caso particular (Operation).
- **+** **`apiVersion` versiona o formato** independentemente das entidades → o catálogo evolui sem quebrar
  consumidores (dual-read no breaking).
- **+** Extensível a assets (Fase 5) **sem novo envelope** — só registra o kind aqui e o `spec` na ADR-014.
- **−** Camada de indireção a mais (envelope + relations projetadas) sobre os `spec` da ADR-009 — custo de
  ingest e de manter a projeção `spec→relations` consistente.
- **−** Enum fechado de kinds/verbos: qualquer entidade/relação nova exige ADR (rigidez proposital, mas real).
- **−** Duplicação aparente `metadata.lifecycle` (envelope) × campos da ADR-009 até o seed ser 100%
  reprojetado no envelope (transitório, igual à duplicação da ADR-009 D9.10).

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|---|---|
| **Sem meta-modelo — cada kind seu próprio envelope** | Recria o acoplamento da ADR-009 um nível acima; Discovery precisaria conhecer N formatos; sem query cross-kind. |
| **Reusar o schema da Operation (ADR-009) como base para tudo** | Operation é específica (`authz`/`risk`/`contract`); assets (Runbook/Persona) não cabem; envelope tem de ser mais fino que qualquer `spec`. |
| **Relações como campos livres no `spec`** | Grafo não navegável de forma genérica; contradiz o `spec` fechado (D10.2); inverso não derivável. |
| **`spec` aberto (aceita campos desconhecidos)** | Quebra o `spec` como contrato governado do PDP; extensão pertence a `annotations`/`labels`, não ao contrato. |
| **`kind` extensível em runtime/config** | Perde governança; um kind é uma decisão de arquitetura (o `spec` precisa de dono/ADR), não um dado. |
| **Versionar por entidade (só `lifecycle`), sem `apiVersion`** | Não permite evoluir o **formato** sem tocar cada entidade; sem dual-read no breaking. |
| **Domain como kind com `spec`** | Domain é dimensão de namespace/ownership (enum da ADR-009), não tem contrato próprio; vira relação `part-of`/`owns`, não entidade. |

## Open questions

- **Namespace default para Tool/Provider:** `providers` (proposto) × por-domínio do provider × por-tenant?
- **`part-of` de Resource:** a hierarquia da ADR-009 (`Organization→Repo→Branch→PR`, `Env→Namespace→Deployment`)
  vira relação `part-of` entre Resources — quem **owns** a taxonomia de Resource kinds (aqui como `metadata`
  ou um sub-registry na ADR-011)?
- **Escopo de unicidade de `name`:** global-por-kind (proposto) × por-tenant quando o catálogo for multi-tenant.
- **Projeção `spec ↔ relations`:** o grafo é **derivado** do `spec` da ADR-009 (single source = spec) ou as
  `relations` de asset (ADR-014) são **autoritativas**? (fronteira de ownership do dado com ADR-014.)
- **Persistência do envelope:** GitOps declarativo × Postgres governado × híbrido — herda a open question da
  ADR-009 D-persistência (decidir junto).

## References

- **ADR-009** (Capability Registry) — define os `spec` dos kinds Core (o **primeiro kind já especificado**);
  este ADR generaliza o envelope/identidade/relations ao redor deles.
- **ADR-011** (Discovery) — **consumidor**: versionamento negociado (`apiVersion`), health, search, inverso de
  relações, estados operacionais derivados (`dangling`/`unhealthy`).
- **ADR-014** (Asset Model) — define os `spec` dos kinds de asset (Runbook/Persona/Policy/Prompt/Template/
  Knowledge) e a **semântica** dos verbos de asset; este ADR **registra os kinds e todos os verbos** (Core +
  asset — D10.4), não os specs nem a semântica de asset.
- **ADR-012** (Event Model) — `resourceVersion`/mudanças do catálogo viram eventos canônicos.
- **ADR-007** (Capability Model) / **ADR-005** (PDP) — consumidores do `spec.authz`/`spec.risk` via envelope.
- **Prior-art:** Backstage Software Catalog (envelope `apiVersion/kind/metadata/spec/relations`, kinds
  fechados, relações tipadas + inverso derivado) · Kubernetes/Crossplane (envelope + `apiVersion`, resource
  model + hierarquia) · OPA/Cedar (attributes no `spec` para policy).
