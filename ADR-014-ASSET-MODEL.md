# ADR-014 — Platform Asset Model

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-010 (kind system / envelope — dono do meta-modelo), ADR-009 (Capability/Operation/Tool/Provider/Resource — assets referenciam), ADR-013 (Runtime — consome Runbook/Persona/Policy), ADR-012 (Event Model — eventos de lifecycle de asset), ADR-005 (PDP consome Policy), ADR-007 (capability model), ADR-011 (Discovery — versão/health)

## Context

A ADR-009 (D9.2) já reservou uma **Fase 5 — Asset Catalog** no Platform Catalog:

```
Platform Catalog (Control Plane)
├── Capabilities · Operations · Tools · Providers · Resources   (Fase 1 — ADR-009)
├── Policies · Runbooks · Personas · Prompts · ADRs · Templates · Knowledge   (Fase 5 — este ADR)
```

Esses sete tipos **já existem, mas espalhados e sem governança**:

- **Runbooks** vivem em `platform-dev-agent/app/dev_agent/runbook/catalog.py` como `RunbookSpec` frozen
  dataclasses versionadas (`version` SemVer), DAGs de tasks que apontam para tools reais do gateway
  (`services-mcp.check_health`, `deploy-mcp.deploy`, …) — mas o catálogo é constante de import-time, sem
  lifecycle, sem dono registrado, sem proveniência.
- **Personas** vivem como `knowledge/profiles/<id>.md` (front-matter YAML + corpo do prompt), lidas em
  runtime por `ProfileBase` — mas não há versão, aprovação nem relação declarada com as capabilities/tools
  que a persona pode chamar (hoje o orquestrador guarda as tools por fora).
- **Prompts** estão embutidos no corpo dos `.md` de persona (sem versão própria, sem reuso, sem eval).
- **Policies** estão parcialmente no `platform_governance.policy_store` (ADR-005) — sem catálogo unificado.
- **ADRs** são arquivos markdown no git (estes) — a **memória arquitetural** não é consultável pela
  plataforma nem ligada às capabilities que decidem.
- **Templates** (scaffolds de repo/serviço, geradores) e **Knowledge** (docs de domínio, runbooks de
  incidente, playbooks) não têm lugar governado.

Consequências: **duplicação e drift** (o mesmo prompt copiado em N personas), **sem auditoria** (quem mudou
a Policy que negou uma execução? qual versão do Runbook rodou?), **sem discovery** (o agente não descobre
"qual runbook faz deploy?" nem "qual persona pode chamar `delivery.service.deploy`?"), e **acoplamento**
(runtime lê arquivos, não um catálogo governado).

A ADR-010 define o **meta-modelo de *kinds*** (o *kind system* e o envelope comum estilo Backstage). A
ADR-009 define o **domínio operacional** (Capability/Operation/Tool/Provider/Resource). Falta a peça do
meio: **como cada tipo de asset é uma instância versionada, governada e relacionada** — o spec de cada
`kind`, seu lifecycle, ownership, proveniência e as **relations** com o domínio operacional. É isso que
este ADR possui.

**Fronteira (crítica para não sobrepor):** `010 = tipos (o kind system e o envelope); 014 = instâncias (o
spec de cada asset dentro do envelope + governança).` Este ADR **USA** o envelope da ADR-010 e **NÃO** o
redefine; **referencia** Capability/Operation/Resource da ADR-009 e **não** os redefine.

## Decision

**D14.1 — Sete kinds de asset governados no catálogo.** O Asset Catalog cobre exatamente estes `kind` (do
kind-system da ADR-010), cada um com um `spec` próprio definido aqui:

| kind | O que é | Referencia (relations) |
|---|---|---|
| `ADR` | decisão arquitetural versionada e consultável | outras ADRs; capabilities/operations afetadas |
| `Prompt` | texto de prompt reutilizável e versionado (unidade de eval) | — (é reutilizado por Persona/Runbook) |
| `Policy` | regra de autz/purpose/HILT como asset (fonte do PDP) | Resources, effects, capabilities (ADR-009/005) |
| `Runbook` | DAG versionado de passos que a plataforma executa | **Operations** (ADR-009), Personas |
| `Persona` | perfil de agente (identidade + prompt + capacidades permitidas) | Prompts, **capabilities/Operations** permitidas |
| `Template` | scaffold/gerador parametrizado (repo, serviço, pipeline) | Operations que aplica; Knowledge |
| `Knowledge` | documento de domínio/playbook indexável (RAG) | qualquer asset (como fonte) |

**D14.2 — Todo asset é uma instância do envelope da ADR-010 (não redefinir).** O envelope comum
(`apiVersion`, `kind`, `metadata{name,namespace,uid,version,labels,annotations,owner,lifecycle}`, `spec`,
`relations`, `resourceVersion`) é **propriedade da ADR-010**. O SemVer do asset é o campo
`metadata.version` do envelope (ADR-010 D10.9), consumido por D14.4. O envelope **não tem** um campo de topo
`status`: o **estado operacional** da entidade é **derivado** pelo Discovery (ADR-010 D10.7 / ADR-011), não
um campo do envelope — este ADR não atribui à ADR-010 campos que ela não define. Aqui só definimos o
**conteúdo do `spec` por kind**, as **relations tipadas** e a **governança**. Exemplo do envelope hospedando
um asset (o `spec` é o que este ADR possui):

```yaml
apiVersion: catalog.platform/v1       # ADR-010
kind: Runbook                          # ADR-010 (kind system)
metadata:                              # ADR-010 (envelope)
  name: deploy_service
  version: 1.0.0                       # SemVer — D14.4
  owner: team:devops                   # D14.5
  lifecycle: active                    # D14.3
spec: { ... }                          # ← ESTE ADR (D14.7)
relations: [ ... ]                     # ← ESTE ADR (D14.6)
provenance: { ... }                    # ← ESTE ADR (D14.9)
```

**D14.3 — Lifecycle canônico de asset (3 estados + sunset).** Este lifecycle (`draft|active|deprecated|sunset`)
é a **especialização, para os kinds de asset, do campo `metadata.lifecycle` do envelope da ADR-010** (D10.7,
enum Core `experimental|stable|deprecated|retired`): os assets curam sua maturidade nesse mesmo campo, com os
estados executáveis próprios de asset. Todo asset percorre:

```
draft ──promote──▶ active ──deprecate──▶ deprecated ──sunset──▶ (archived/removido)
   │                  │                        │
   └── revisão ───────┘                        └── janela de sunset obrigatória p/ Policy/Runbook/Persona
```

- `draft` — editável, **não** consumível pelo runtime/PDP; não precisa de aprovação.
- `active` — **imutável na versão** (mudança = nova versão, D14.4); consumível; requer aprovação (D14.8).
- `deprecated` — ainda resolvível, mas emite `AssetDeprecatedUsed` (ADR-012) e não pode ser referenciado por
  **novos** assets `active`.
- `sunset` — remoção agendada; obrigatório anunciar `sunset_at` e um **substituto** (`superseded_by`) para
  kinds executáveis (Policy/Runbook/Persona) — deny-safe: o runtime falha fechado se o substituto não existe.

**D14.4 — Versionamento imutável (SemVer) + resolução.** `active` é imutável por versão — corrigir é publicar
`x.y.z+1`. Referências entre assets usam **pin** (`deploy_service@1.2.0`) ou **range** (`^1.2`) — kinds
executáveis (Runbook/Policy/Persona) exigem **pin** (reprodutibilidade e auditoria: o `PlanCreated` grava
`runbook_version`, como já faz o runtime hoje); Knowledge/Template podem usar range. Resolução default =
maior `active` que satisfaz o range, nunca `deprecated`/`draft`.

**D14.5 — Ownership obrigatório.** Todo asset tem `owner` (grupo/time, não indivíduo — `team:<x>`) herdado do
envelope (ADR-010). O owner é o **único** autorizado a promover/deprecar/sunset (D14.8) e é o destinatário do
alerta de sunset. Sem owner → o asset não sai de `draft` (INV de ingestão).

**D14.6 — Relations tipadas ligam asset ↔ domínio (referência, nunca cópia).** As relações são **arestas
tipadas** no envelope (ADR-010), resolvidas contra o catálogo operacional (ADR-009) e outros assets. O
**registro dos verbos é da ADR-010 D10.4** (autoridade — é lá que o conjunto de verbos é fechado); esta ADR
**não define um conjunto próprio**, apenas **especifica a semântica** dos verbos de asset já registrados lá:

| relation | de → para | Semântica |
|---|---|---|
| `executes` | Runbook → Operation (ADR-009) | cada passo do DAG referencia uma **Operation** (id canônico), não a Tool |
| `runAs` | Runbook → Persona | perfil responsável pela execução do runbook |
| `allows` | Persona → Capability/Operation | conjunto de capacidades que a persona **pode** invocar (allow-list) |
| `uses` | Persona → Prompt | o prompt (versionado) que compõe o system prompt |
| `governs` | Policy → Resource/effect/Capability | alvo da regra (ADR-005/009) — resource+effect, não tool |
| `supersedes` | qualquer → qualquer (mesmo kind) | substituição em sunset (D14.3) |
| `derivedFrom` | Template → Operation/Knowledge | o que o scaffold aplica/consulta |
| `sources` | qualquer → Knowledge | fonte de contexto (RAG) |
| `decides` | ADR → Capability/Operation | a decisão que rege aquela capacidade (memória arquitetural consultável) |

Regra de integridade: uma relação para um asset/Operation **inexistente ou não-`active`** bloqueia a
promoção do asset de origem (validação na ingestão, D14.10). `Runbook.executes` deve resolver para uma
**Operation** válida da ADR-009 (não a uma Tool) — assim o runbook herda portabilidade de provider (D9.3).

**D14.7 — Spec por kind (o conteúdo que este ADR possui).** Cada kind fixa os campos do seu `spec`:

<details><summary><b>Runbook</b> — DAG versionado sobre Operations</summary>

```yaml
spec:
  intent: "Deploy de serviço com pré-check, testes, deploy (N2) e verificação"
  responsible_profile: devops        # → relation runAs (Persona)
  tasks:                             # DAG; key = task_id
    check_health:
      title: "Pre-deploy health check"
      operation: observability.service.health   # → relation executes (Operation, ADR-009) — NÃO tool
      required: true
      inputs: { service: {type: string} }       # JSON Schema
      depends_on: []
      capability_override: null                  # opcional; senão deriva da Operation (ADR-009 authz)
      risk_override: null
    deploy:
      title: "Deploy the service (HIGH RISK)"
      operation: delivery.service.deploy
      required: true
      depends_on: [check_health]
      # approval e risk NÃO são redefinidos aqui: vêm da Operation (ADR-009 risk/authz).
```

Nota de aterramento: espelha o `RunbookSpec`/`RunbookTaskSpec` real (`catalog.py`, versionado, DAG por
`depends_on`), com a mudança-chave de a task apontar para a **Operation** (ADR-009), não para o `tool` cru —
o binding Operation→Tool é resolvido pelo catálogo (D9.5). `capability_override`/`risk_override` seguem
existindo como *pin* de exceção.
</details>

<details><summary><b>Persona</b> — identidade + prompt + allow-list de capacidades</summary>

```yaml
spec:
  display_name: "DevOps Engineer"
  model: claude-sonnet-4-6           # default; front-matter da persona pode sobrepor
  max_iterations: 12
  prompt_ref: prompt:devops.system@2.1.0     # → relation uses (Prompt), não texto embutido
  allowed_capabilities:              # → relation allows (allow-list explícita)
    - observability.service.health
    - delivery.service.deploy
    - testing.suite.run
  knowledge_refs: [kb:devops-playbook@^1]     # → relation sources
```

Nota de aterramento: hoje a persona é `knowledge/profiles/<id>.md` (front-matter + corpo lido por
`ProfileBase`) e as tools são guardadas **por fora** pelo orquestrador. Este ADR torna o **allow-list de
capacidades um campo declarado do asset** (`allowed_capabilities`) — o enforcement continua no PDP/orquestrador
(ADR-005), mas a intenção passa a ser **catalogada e auditável**, e o prompt vira um asset `Prompt`
referenciado (fim da cópia embutida).
</details>

<details><summary><b>Policy</b> — regra de autz/purpose/HILT como asset (fonte do PDP)</summary>

```yaml
spec:
  effect: deny                       # allow | deny
  target:                            # → relation governs (ADR-009/005) — resource+effect, não tool
    resource: service
    effects: [deploy, delete]
    blast_radius_gte: environment
  condition: "purpose != 'incident_response' && env == 'production'"
  requires_approval: N2              # none|N1|N2 (HILT ADR-005) — reforça, não substitui a Operation
  purpose_binding: [lgpd]            # ADR-005 purpose/mandate
```

Nota: a Policy é **asset versionado** (proveniência/aprovação/sunset), consumido pelo PDP (ADR-005). Ela
**não** redefine o modelo de risco da Operation (ADR-009 D9.8) — sobrepõe/reforça por atributo (estilo
OPA/Cedar), casando `resource`+`effects`+`blast_radius`.
</details>

<details><summary><b>Prompt</b> — texto reutilizável e versionado (unidade de eval)</summary>

```yaml
spec:
  role: system                       # system | few_shot | tool_hint
  template: "Você é um engenheiro DevOps... {{context}}"
  variables: [context]               # placeholders
  eval_ref: kb:devops-prompt-evals@^1   # opcional — liga a suíte de avaliação
```
</details>

<details><summary><b>Template</b> — scaffold/gerador parametrizado</summary>

```yaml
spec:
  target: repository                 # repository | service | pipeline | adr
  parameters: { name: {type: string}, stack: {enum: [python, node]} }
  applies: [development.repo.scaffold]   # → relation derivedFrom (Operations que executa)
  artifact: "git://templates/service-python@1"   # onde vive o corpo do template
```
</details>

<details><summary><b>Knowledge</b> — documento indexável (RAG)</summary>

```yaml
spec:
  format: markdown                   # markdown | pdf | url
  source: "git://knowledge/devops-playbook.md"
  index:                             # metadados de recuperação
    embeddings: true
    tags: [devops, incident, runbook]
```
</details>

<details><summary><b>ADR</b> — decisão arquitetural consultável</summary>

```yaml
spec:
  title: "Platform Asset Model"
  status: proposed                   # proposed | accepted | superseded
  decides: [development.*, delivery.service.deploy]   # → relation decides (Capabilities/Operations)
  body: "git://ADR-014-ASSET-MODEL.md"
```

Nota: cataloga a ADR como **memória arquitetural consultável** — `find_by_decides(capability)` responde
"que decisão rege esta capacidade?". O corpo continua no git (fonte única); o catálogo indexa e liga.
</details>

**D14.8 — Governança: quem move o lifecycle e como.** Transições de lifecycle são **ações governadas**:

| Transição | Quem | Gate |
|---|---|---|
| `draft → active` (**promote**) | `owner` (D14.5) | revisão + **aprovação** (N1 default; **N2** para Policy e Runbook com passo `write`/`blast_radius≥environment`) |
| `active → deprecated` (**deprecate**) | `owner` | aviso; exige apontar `superseded_by` se houver consumidores ativos |
| `deprecated → sunset` | `owner` | **N2**; obrigatório `sunset_at` + substituto para kinds executáveis (D14.3) |
| edição de `draft` | qualquer com escrita no namespace | nenhum |

A promoção **valida as relations** (D14.6/D14.10) antes de permitir `active`. Cada transição emite evento
(D14.11) e grava proveniência (D14.9). O gate de aprovação reusa o **ApprovalGate N1/N2 do runtime** (ADR-013)
— não se cria um mecanismo novo.

**D14.9 — Proveniência obrigatória (auditoria + reprodutibilidade).** Todo asset carrega:

```yaml
provenance:
  created_by: user:caiog | agent:planner
  created_at: 2026-07-05T12:00:00Z
  source: git://path | api | ingested_from:<runtime-file>   # de onde veio (seed/ingestão)
  revision: sha256:...              # hash do spec resolvido (imutabilidade da versão)
  approvals: [{by: team:devops, level: N2, at: ...}]        # trilha de D14.8
  supersedes: runbook:deploy_service@1.1.0                  # linhagem
```

Isto responde "que versão rodou, quem aprovou, de onde veio" — hoje impossível para runbooks/personas em
arquivo.

**D14.10 — Ingestão aditiva a partir do estado real (seed), com validação.** Como na ADR-009 D9.10
(não-destrutivo): o Asset Catalog é populado **por cima** do que já existe —

- Runbooks ← `RunbookSpec` de `catalog.py` (id, version, DAG); `task.tool` é **resolvido para a Operation**
  correspondente (ADR-009) na ingestão; o que não resolver entra `draft` com flag `unresolved_operation`.
- Personas ← `knowledge/profiles/<id>.md` (front-matter → `spec`; corpo → asset `Prompt` extraído).
- Policies ← export do `platform_governance.policy_store` (ADR-005).
- ADRs ← os arquivos `ADR-0XX-*.md` do repo.

O runtime lê o catálogo com **fallback** para os arquivos durante a transição (paridade com D9.10). Validação
de ingestão: `owner` presente, versão SemVer, relations resolvíveis → senão fica `draft` e não é consumível.

**D14.11 — Eventos de lifecycle (delega o modelo à ADR-012).** As transições emitem eventos canônicos —
`AssetPublished`, `AssetPromoted`, `AssetDeprecated`, `AssetSunset`, `AssetDeprecatedUsed`,
`AssetValidationFailed`. Esses **seis types e o tópico `platform.asset.v1` já estão registrados na taxonomia
da ADR-012 (D12.3/D12.5)** — cujo **envelope/transporte é propriedade da ADR-012** (Kafka `dataforall-kafka`).
Este ADR é a **emissora e dona da semântica** (nomeia os eventos, fixa o gatilho de cada transição em
D14.3/D14.8); **não** define o schema de evento nem o transporte (cross-ref bidirecional com a ADR-012).

## Consequences

- **+** Runbooks/Personas/Policies/Prompts/ADRs deixam de ser arquivos soltos e viram **assets versionados,
  governados e consultáveis** — auditoria (quem/qual versão/aprovado por quem) e discovery ("qual runbook faz
  deploy?", "que persona pode `delivery.service.deploy`?", "que ADR decide esta capability?").
- **+** **Fim do drift de prompt**: `Prompt` é asset referenciado (`uses`), não copiado em cada persona.
- **+** `Runbook.executes → Operation` (não Tool) faz o runbook **herdar a portabilidade de provider** da
  ADR-009 (D9.3) — trocar `deploy-mcp` por `argo` não reescreve runbooks.
- **+** Lifecycle + proveniência dão **reprodutibilidade** (o plano grava a versão pinada, como o runtime já
  faz) e **sunset seguro** (deny-fechado com substituto).
- **+** Reusa mecanismos existentes (ApprovalGate N1/N2 do runtime, policy_store, Kafka) em vez de criar novos.
- **−** **Curadoria inicial** dos assets (owner, versão, relations) — mitigado pelo seed aditivo (D14.10) e por
  campos avançados incrementais.
- **−** **Duplicação transitória** (asset no catálogo *e* arquivo no repo) até o catálogo ser autoritativo —
  mesmo custo aceito na ADR-009.
- **−** Acoplamento de escrita ao meta-modelo da ADR-010 (envelope) e ao domínio da ADR-009 (Operations): uma
  mudança de envelope propaga aos specs — mitigado por `apiVersion` no envelope.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|---|---|
| **Manter assets em arquivos (git only), sem catálogo** | Sem versão governada, sem aprovação, sem discovery, sem proveniência; drift de prompt; runtime acoplado a arquivos. |
| **Um catálogo de assets separado do Platform Catalog** | Duas fontes de verdade; relations asset↔Operation ficariam cross-store e frágeis. A ADR-009 já reservou a Fase 5 no mesmo catálogo. |
| **Redefinir o envelope/kinds aqui** | Invade a ADR-010 (dona do kind system). Este ADR só define `spec`/relations/governança das instâncias. |
| **Runbook.task aponta direto para a Tool (como hoje)** | Acopla o runbook ao provider; perde a portabilidade da ADR-009 (gap #4). Apontar para a Operation resolve. |
| **Persona com tools embutidas (estado atual)** | Allow-list implícita e não-auditável; prompt copiado. Declarar `allowed_capabilities` + `prompt_ref` torna a intenção catalogável. |
| **Policy como permissão por-tool (enum)** | Fragmenta o authz (rejeitado em ADR-007/009); Policy governa `resource`+`effect`+`blast_radius`. |
| **Lifecycle livre (sem sunset obrigatório)** | Assets executáveis (Policy/Runbook/Persona) órfãos quebram execuções silenciosamente; sunset com substituto falha-fechado. |

## Open questions

- **Persistência dos assets:** declarativo em git (GitOps) × Postgres governado × híbrido — herda a mesma
  open question da ADR-009 (deveriam decidir juntas).
- **Corpo vs metadados:** o corpo (prompt/knowledge/template/ADR) fica **no git** (referenciado por `source`)
  ou **inline** no catálogo? Proposta: git para corpo grande, inline para specs pequenos.
- **Eval de Prompt/Persona como gate de promoção:** `eval_ref` deve **bloquear** `draft→active` abaixo de um
  score? (depende de infra de eval — talvez fase posterior).
- **Namespacing de assets × domínios da ADR-009:** um asset pertence a um domínio? Ou namespace próprio
  (`team:`/`product:`)? Casar com ownership de domínio (open question da ADR-009).
- **Multi-tenant:** assets por-tenant × globais × herança (relevante se virar produto — ADR-008 N6).
- **Quem resolve `Runbook.executes` na ingestão** quando um `tool` legado não mapeia a nenhuma Operation
  existente — cria Operation `draft` automaticamente ou exige curadoria?

## References

- ADR-010 (kind system / envelope) — **dono do meta-modelo**; este ADR hospeda `spec` no envelope dele
- ADR-009 (Capability Registry) — Operations/Resources que os assets referenciam; reservou a Fase 5 (D9.2)
- ADR-013 (Runtime) — consumidor de Runbook/Persona; fornece o ApprovalGate N1/N2 reusado em D14.8
- ADR-012 (Event Model) — dono do envelope dos eventos de lifecycle nomeados em D14.11
- ADR-005 (PEP/PDP) — consumidor primário de Policy · ADR-007 (capability model) — base de authz/risk
- ADR-011 (Discovery) — versão/health/search dos assets no catálogo
- Aterramento real: `platform-dev-agent/app/dev_agent/runbook/catalog.py` (`RunbookSpec` versionado, DAG),
  `knowledge/profiles/<id>.md` + `ProfileBase` (persona = front-matter + prompt), `platform_governance.policy_store`
- Prior-art: Backstage (software/asset catalog, `kind`+`spec`+`relations`), OPA/Cedar (policy-as-attributes),
  SemVer (versionamento), GitOps (proveniência declarativa)
