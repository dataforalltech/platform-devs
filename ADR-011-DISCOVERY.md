# ADR-011 — Discovery

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-010 (kinds que se descobrem), ADR-009 (Capability/Operation/Tool/Provider/Resource — source of truth), ADR-008 (era north-star), ADR-005 (PDP consome discovery), ADR-006 (transporte no Tool binding), ADR-012 (eventos de health/deprecação), ADR-013 (planner/executor consomem)

## Context

A ADR-009 estabeleceu o **Platform Catalog** como source of truth (Capability ⊃ Operation ──1..N──▶ Tool ──▶ Provider, Operation atua sobre Resource) e listou uma **Discovery API** (D9.9: `get` · `search` · `list_by_domain` · `find_by_resource` · `find_by_effect` · `find_by_owner` · `find_by_risk` · `list_tools_for`) como *decisão travada*, mas deixou o **contrato de consulta** por especificar. Deixou também **duas open questions** que travam consumidores reais:

1. **Seleção de Tool** quando N Tools implementam a mesma Operation (`preference`/`cost`/`latency`/`health`).
2. **Versionamento & compatibilidade** das Operations e a resolução quando há N versões.

Isto é o gap entre "o catálogo existe" e "o catálogo é **consumível em runtime**". Sem ele:

- O **planner** (ADR-013, `PlanBuilder`) monta um plano contra uma Operation, mas não sabe **qual Tool concreta** vai executá-la nem se o Provider está **vivo**.
- O **PDP** (ADR-005) precisa de um `get(operation_id)` **estável e versionado** para casar policy contra o contrato correto — não contra "a última versão que por acaso está no catálogo".
- A **descoberta por humano/agente** (o gap #2 da ADR-009: 298→1200 tools) precisa de `search`/`list_by_domain` com semântica definida, não de listar 298 funções.

**Fundação latente real** (aterramento, não invenção): o `mcp-registry.py` (`:8000`) já faz *service discovery* de providers — poll de `GET /v1/health` por serviço com **cache TTL de 30 s**, agregando `status=online/offline`, `tools`, `version`. É health **de provider**, granular por serviço, mas **não por Operation** e sem semver/compat. O grafo de ecossistema do `ai-governance-mcp` (`query_ecosystem_graph`, `find_dependencies_of`) dá resources/dependências. O `CapabilityResolver` do `platform-dev-agent` (hoje repo standalone `platform-devs-agent`, pacote `app/devs_agent`) já resolve read/write + risk **estruturalmente**. Discovery **promove** esse health de provider a um plano de leitura do catálogo (health de Operation + seleção de Tool) — **não** reescreve o runtime.

**Papel:** Discovery é o **Backstage** desta plataforma — a fachada de leitura/consulta/resolução sobre o catálogo da ADR-009. Concretiza o N1 (Service Discovery de plataforma) que a ADR-008 tinha como north-star.

## Decision

### D11.1 — Discovery é uma **fachada de leitura**, não uma segunda fonte da verdade
O catálogo (ADR-009) é a autoridade. Discovery é uma **read API** (query + resolução + health) por cima. **Não** escreve Operation/Tool/Provider, **não** define kinds (ADR-010), **não** emite eventos (ADR-012). Toda consulta é *side-effect-free* e cacheável.

### D11.2 — Contrato da Discovery API (concretiza a D9.9)
Assinaturas estáveis; `q` é *free-text* sobre `id`/`tags`/`description`/`resource`. Filtros combináveis via `list(**filters)`.

| Método | Assinatura | Retorna | Consumidor primário |
|---|---|---|---|
| `get` | `get(id, version=None) -> Operation` | 1 Operation resolvida (ver D11.5) | PDP (ADR-005), planner (ADR-013) |
| `search` | `search(q, *, domain=None, limit=50) -> [OperationRef]` | ranqueado por relevância + `lifecycle` + `health` | humano/agente, UI de catálogo |
| `list_by_domain` | `list_by_domain(domain) -> [OperationRef]` | Operations de um domínio | descoberta, ownership |
| `find_by_resource` | `find_by_resource(resource_type, *, parent=None) -> [OperationRef]` | quem opera sobre o recurso | impact analysis |
| `find_by_effect` | `find_by_effect(effect) -> [OperationRef]` | ex. tudo que `deploy`/`delete` | policy, blast-radius review |
| `find_by_owner` | `find_by_owner(owner) -> [OperationRef]` | catálogo por time | governança |
| `find_by_risk` | `find_by_risk(level) -> [OperationRef]` | ex. `critical` | auditoria, HILT tuning |
| `list_tools_for` | `list_tools_for(operation_id, *, version=None, healthy_only=False) -> [ToolBinding]` | Tools que implementam a Operation, **ordenadas pela política de seleção (D11.6)** | planner/executor |
| `resolve_tool` | `resolve_tool(operation_id, *, version=None, constraints=None) -> ToolBinding` | **a Tool escolhida** (aplica D11.6) | planner/executor |
| `health` | `health(*, provider_id=None, operation_id=None) -> HealthReport` | liveness agregado (D11.7) | planner, ops, SLO |

`OperationRef` = `{id, version, domain, capability, resource, default_level, lifecycle, health_summary}` (projeção leve p/ listagem — não infla o payload de 1200 Operations com o contrato inteiro).

### D11.3 — Versionamento: **SemVer na Operation**, imutável por versão
A **Operation** (contrato de domínio, D9.4) é versionada por **SemVer** — o id canônico `<domain>.<resource>.<operation>` ganha uma dimensão de versão. Esse SemVer **vive em `metadata.version` do envelope da ADR-010** (D10.9, eixo "Entidade"); Discovery **consome** esse campo, não o define. **Cada versão publicada é imutável** (um contrato é congelado; mudanças criam uma nova versão).

```yaml
id: delivery.service.deploy
metadata:
  version: 2.1.0          # SemVer da OPERATION (contrato de domínio) — envelope ADR-010 (metadata.version); imutável quando publicada
```

Regra de bump (ADR-009 D9.4 = o que muda):

| Mudança no contrato | Bump | Compat |
|---|---|---|
| `outputs` ganham campo opcional; nova `precondition` derivável; `tags`/`examples`/`cost` | **patch/minor** | retrocompatível |
| `inputs` ganham campo **opcional**; novo `effect` non-breaking; `retry_policy` relaxada | **minor** | retrocompatível |
| `inputs` ganham obrigatório / removem campo; muda `authz.capability`; sobe `default_level`/`approval_required`; `resource.type` muda | **major** | **breaking** |

`provider_version` (D9.5) é **ortogonal**: é a versão do *binding técnico* e **não** dita a versão da Operation. Um bump só de provider (mesmo contrato) **não** muda a versão da Operation.

### D11.4 — Compatibilidade: consumidor declara um **range**, resolução por SemVer
Um consumidor (planner, PDP, runbook) referencia uma Operation por **id + range** (`caret`/`tilde`/exato). A ausência de range = "**última `stable` compatível**".

```yaml
uses:
  - operation: delivery.service.deploy
    version: "^2.0.0"     # aceita 2.x.y estável mais recente; NUNCA 3.x (breaking)
```

- **`get(id)` sem versão** ⇒ **maior `stable` publicada** (nunca `experimental`/`deprecated`).
- **`get(id, "^2.0.0")`** ⇒ maior `stable` que satisfaz o range.
- Nenhuma versão satisfaz o range ⇒ erro **explícito** de discovery (`OperationVersionNotFound`) — **nunca** cai silenciosamente numa major diferente. Determinismo é a garantia central p/ o PDP.

### D11.5 — Deprecação com **janela e sucessor** (lifecycle)
Estende `metadata.lifecycle` (`experimental|stable|deprecated|retired` — enum do envelope da ADR-010 D10.7)
com o **contrato de deprecação**. Não removemos; **anunciamos**.

```yaml
metadata:
  lifecycle: deprecated
  deprecation:
    since: "2026-06-01"
    sunset: "2026-12-01"        # data alvo de remoção (fim da resolução por default)
    superseded_by: delivery.service.deploy@3.0.0   # migração recomendada
    reason: "resource.type migrou de service p/ workload (D11.3 major)"
```

Regras: (a) uma versão `deprecated` **continua resolvível** por range explícito até `sunset`; (b) `get`/`search` sem range **nunca** escolhem `deprecated`; (c) `search` marca `deprecated` no `OperationRef` para a UI; (d) a **transição `stable→deprecated` e `experimental→stable`** é um evento de catálogo (emitido pela ADR-012 — Discovery só **expõe** o estado atual, não publica).

### D11.6 — **Política de seleção de Tool** (resolve a open question #1 da ADR-009)
Quando N Tools implementam a mesma Operation (`list_tools_for`), a escolha (`resolve_tool`) é **determinística** e por metadata no Tool binding (D9.5) — sem heurística oculta:

```yaml
# Tool binding (estende D9.5) — campos de seleção
operation_id: delivery.service.deploy
provider_id: deploy-mcp
provider_version: 1.2.0
tool: deploy
endpoint: streamable-http          # ADR-006
selection:
  preference: 100                  # peso base do operador (maior vence) — expressa intenção
  weight: 1.0                      # split ponderado entre empatados (multiplex/canário)
  cost: medium                     # low|medium|high — desempata p/ baixo custo
  latency: async                   # sync-fast|sync|async — desempata p/ mais rápido
  enabled: true                    # kill-switch por binding
```

**Ordem de decisão (lexicográfica, curto-circuita no primeiro critério que separa):**

```
1. health          — descarta UNHEALTHY (D11.7); DEGRADED só se não houver HEALTHY
2. enabled         — descarta enabled=false (kill-switch)
3. constraints     — respeita constraints do chamador (ex. require provider_id, forbid effect)
4. preference      — maior preference vence (intenção explícita do operador)
5. cost, latency   — desempate: menor custo, depois menor latência
6. weight          — entre os ainda empatados: escolha ponderada estável por (weight, run_id)
                     → determinística dentro de um run; permite canário/split
7. provider_version — desempate final: maior SemVer
```

`resolve_tool(..., constraints={"provider_id": "argo"})` **fixa** o provider (pinning p/ debug/rollback). Se nada satisfaz ⇒ `NoHealthyToolForOperation` (erro explícito; o planner decide fallback/abort — ADR-013). Isto dá **portabilidade real** ao gap #4 da ADR-009: trocar `deploy-mcp`→`argo` é mudar `preference`/`enabled`, sem tocar domínio nem consumidores.

### D11.7 — Health/liveness em **dois níveis** (Provider e Operation)
Promove o poll de `/v1/health` do `mcp-registry.py` (`:8000`, TTL 30 s) a um modelo de dois níveis, **derivado**, não uma nova fonte:

| Nível | Origem | Estados | Semântica |
|---|---|---|---|
| **Provider** | poll `GET /v1/health` (existente) + circuito do gateway | `HEALTHY` · `DEGRADED` · `UNHEALTHY` · `UNKNOWN` | o processo/endpoint MCP responde? |
| **Operation** | **derivado**: ⋁ dos Tools que a implementam | `SERVED` (≥1 Tool HEALTHY) · `DEGRADED` (só DEGRADED) · `UNSERVED` (0 utilizável) | a capacidade de domínio está disponível **por algum** provider? |

```yaml
HealthReport:
  operation_id: delivery.service.deploy
  operation_status: SERVED
  tools:
    - provider_id: deploy-mcp   status: HEALTHY    last_check: 2026-07-05T12:00:03Z   latency_ms: 42
    - provider_id: argo         status: DEGRADED   last_check: 2026-07-05T12:00:01Z   reason: "5xx rate 8%"
  checked_at: 2026-07-05T12:00:03Z
  ttl_s: 30                      # herdado do cache do mcp-registry
```

- Health é **input da seleção** (D11.6 passo 1): uma Operation `UNSERVED` faz `resolve_tool` levantar `NoHealthyToolForOperation`.
- Health é **cacheado** (TTL 30 s, como hoje) — Discovery **lê** cache, não sonda em cada `get` (previsibilidade de latência p/ o PDP).
- Discovery **expõe** o estado; **transições** de health (`ProviderUnhealthy`, `OperationUnserved`) são **eventos** (ADR-012), fora do escopo deste ADR.

### D11.8 — Metadata para descoberta (o que torna `search`/`list_*` úteis)
Discovery **consome** a `metadata` da Operation (D9.4: `tags`, `owner`, `lifecycle`, `cost`, `latency`) e o `resource`/`effects`/`risk` — **não** adiciona campos novos ao schema (isso é ADR-010/ADR-009). Contribuição própria de Discovery: **como esses campos são indexados/ranqueados** — `search` ranqueia por (match textual em `id`/`tags` > `resource` > `description`), depois desempata por `lifecycle` (`stable`>`experimental`, `deprecated` ao fim) e `health` (`SERVED` antes de `UNSERVED`).

### D11.9 — Ingestão & frescor do índice (fronteira com o catálogo)
Discovery indexa **a partir** do catálogo (ADR-009 D9.10 — seed do audit dos 298 tools) e do health do `mcp-registry`. O índice é **read-through com cache**: mudanças de catálogo (nova Operation/versão/deprecação) invalidam a entrada; health tem TTL próprio (30 s). Durante a transição (D9.10), `list_tools_for` faz **fallback** ao `tools/list` do provider quando a Operation ainda não tem Tool binding no catálogo. **Quem escreve no catálogo (push vs pull) é open question da ADR-009 — não é resolvido aqui.**

## Consequences

- **+** O catálogo deixa de ser "armazenado" e passa a **consumível**: contrato de query estável (D11.2) p/ PDP, planner e humanos.
- **+** **Portabilidade efetiva** — `resolve_tool` + `selection` concretizam o gap #4 da ADR-009 (N providers p/ 1 Operation) de forma determinística e auditável.
- **+** **Versionamento explícito** (D11.3/11.4) dá ao PDP um `get` determinístico: policy casa contra o contrato certo, não contra "o mais novo".
- **+** **Deprecação com sunset** (D11.5) permite evoluir contratos sem quebrar consumidores de repente.
- **+** Health de **Operation** (não só de Provider) responde a pergunta que o planner realmente faz: "consigo executar esta capacidade agora?".
- **+** Reusa o poll/TTL do `mcp-registry.py` — evolução, não rewrite.
- **−** Manter `selection` (preference/weight/cost/latency) por binding é **curadoria** adicional (mitigado: defaults sãos ⇒ maior preference/maior versão).
- **−** SemVer por Operation exige **disciplina de bump** (D11.3) — um major mal-classificado quebra consumidores; precisa de lint no pipeline de publicação (fora deste ADR).
- **−** Cache de 30 s ⇒ janela em que Discovery aponta p/ um provider recém-caído (aceitável; o executor trata falha de tool como item ERROR, não aborta o plano — ADR-013).
- **−** Um índice a operar/monitorar (latência de `search` sobre 1200 Operations) — projeção leve (`OperationRef`) e cache mitigam.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|---|---|
| **Sem versão (Operation sempre "a última")** | PDP não-determinístico; deprecação impossível; um bump breaking derruba todos os consumidores silenciosamente. |
| **Versionar a Tool/provider, não a Operation** | Acopla contrato de domínio à implementação (regride ao gap da ADR-009); consumidor teria de saber de provider p/ pedir contrato. |
| **Seleção de Tool no runtime por heurística (ex. "primeiro que responde")** | Não-determinístico e não-auditável; impossível fixar/rollback; contradiz o `resume_writes_safe` por-metadata da D9.8. |
| **Health só de Provider (como hoje no `mcp-registry`)** | Não responde "a Operation está servível?"; planner teria de reimplementar o ⋁ dos Tools. |
| **Discovery como 2ª fonte da verdade (write API)** | Duplica autoridade com o catálogo (ADR-009); duas fontes divergem. Discovery é read-only por decisão. |
| **Discovery emite eventos de health/deprecação** | É escopo da ADR-012; Discovery só expõe estado (fronteira limpa). |
| **Range de compat resolvido no cliente** | Cada consumidor reimplementa SemVer; divergência. Resolução centralizada em `get` é a garantia de determinismo. |

## Open questions

- **Peso do `health` no ranqueamento de `search`** (vs relevância textual) — quanto rebaixar `DEGRADED`/`UNSERVED` na listagem humana.
- **Granularidade do health de Operation** por Resource/tenant (uma Operation pode estar `SERVED` num tenant e `UNSERVED` noutro) — herda da hierarquia de `resource` (ADR-009 D9.4, ainda opcional).
- **Enforcement do bump SemVer** (lint de contrato no pipeline de publicação): dono do gate? (relaciona ADR-010).
- **Split por `weight` (canário) determinístico por `run_id`** vs por `tenant`/`session` — qual chave de sticky.
- **`sunset` como hard-stop** (bloqueia resolução) vs soft (só warning): decisão de política — pode migrar p/ ADR-012 (evento) + ADR-005 (deny).

## References

- ADR-009 (Capability Registry) — source of truth; D9.9 (Discovery API listada), D9.5 (Tool binding), D9.4 (Operation/lifecycle), open questions (seleção de Tool, ingestão push/pull) que este ADR resolve/delimita
- ADR-008 (North-Star) — N1 (Service Discovery de plataforma), aqui concretizado
- ADR-010 (Kinds) — os *kinds* que Discovery lista/versiona (não redefinidos aqui)
- ADR-012 (Event Model) — transições de health/deprecação como eventos (Discovery expõe estado, não emite)
- ADR-013 (Runtime) — planner/executor consomem `get`/`resolve_tool`/`health`; fallback e resume-safety
- ADR-005 (PEP/PDP) — consumidor primário do `get(id, version)` determinístico
- `mcp-registry.py` (`:8000`) — poll `GET /v1/health`, cache TTL 30 s (base do D11.7) · ai-governance ecosystem graph (resources/dependências)
- Prior-art: Backstage (software catalog + discovery), SemVer 2.0.0, Consul/SPIFFE (health + service resolution), Envoy/xDS (weighted endpoint selection)
