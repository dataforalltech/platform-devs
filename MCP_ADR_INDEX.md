# MCP Platform — Índice de ADRs (Auth / Autz / Transporte / Capabilities)

**Status:** Active index
**Date:** 2026-07-05
**Authors:** caiog
**Escopo:** cross-repo — `platform-devs`, `platform-auth`, `platform-governance`, `platform-admin`, `platform-marketing`

> A ADR-003 monolítica original ("MCP Auth Architecture") foi **dividida** em ADRs focadas,
> por recomendação de revisão de arquitetura, para reduzir acoplamento e permitir evolução
> independente de cada camada. Este arquivo é o **ponto de entrada** e a **base compartilhada**
> (diagnóstico, tese central, arquitetura-alvo). As decisões vivem nas ADRs abaixo.

---

## As ADRs

| ADR | Tema | Corte |
|---|---|---|
| [ADR-003](ADR-003-MCP-IDENTITY.md) | **Identidade MCP** — classes (human/service/machine/agent), AS canônico, borda | **V1** |
| [ADR-004](ADR-004-MCP-TWIN-TOKEN-EXCHANGE.md) | **Twin Token / Token Exchange** — RFC 8693, capability token efêmero | **V1** |
| [ADR-005](ADR-005-MCP-PEP-PDP.md) | **PEP/PDP** — TwinPep, GuardedToolRegistry, HILT, output policy | **V1** |
| [ADR-006](ADR-006-MCP-TRANSPORTS.md) | **Transportes** — Streamable HTTP + compat SSE/stdio + matriz de clientes | **V1** |
| [ADR-007](ADR-007-MCP-CAPABILITY-MODEL.md) | **Capability Model** — tool→capability, scope, risk tier, workload identity, session | **V1** |
| [ADR-008](ADR-008-MCP-NORTH-STAR.md) | **North-Star** — discovery, registries, trust domains, cost/rate policy, federação | **North-Star** |
| [ADR-009](ADR-009-CAPABILITY-REGISTRY.md) | **Capability Registry** — registry como source of truth; catálogo por domínio/recurso/operação; MCP servers viram providers | **Fase 1** |
| [ADR-010](ADR-010-PLATFORM-CATALOG.md) | **Platform Catalog** — meta-modelo de *kinds* (envelope + kinds Core/Asset + relations tipadas) | **Control Plane** |
| [ADR-011](ADR-011-DISCOVERY.md) | **Discovery** — API de consulta, versionamento/compat, health, seleção de Tool | **Control Plane** |
| [ADR-012](ADR-012-EVENT-MODEL.md) | **Event Model** — taxonomia canônica + envelope CloudEvents + Kafka | **Control Plane** |
| [ADR-013](ADR-013-RUNTIME.md) | **Runtime** — Planner/Approver/Executor/Scheduler/Memory/Budget/Recovery formalizados | **Control Plane** |
| [ADR-014](ADR-014-ASSET-MODEL.md) | **Asset Model** — ADR/Prompt/Policy/Runbook/Persona/Template/Knowledge como assets versionados | **Control Plane** |

**Corte:** V1 = segurança correta e executável agora. Fase 1 = primeira etapa concreta do north-star
(promove o `mcp-registry.py`; destrava discovery/policy/governança sem reescrever o runtime).
North-Star = visão de plataforma comercial/referência.
A decisão estratégica **plataforma interna × produto comercial** afeta a **prioridade do ADR-008**,
**não** a arquitetura correta da base (003–007). Por isso a V1 não fica travada por essa decisão.

---

## Visão por camadas (como as ADRs se conectam)

| Camada | ADRs | Papel |
|---|---|---|
| 1 · Identity | ADR-003, ADR-004 | classes de identidade + capability token efêmero |
| 2 · Authorization | ADR-005, ADR-007 | PEP/PDP + modelo de capability/risk |
| 3 · Transport | ADR-006 | Streamable HTTP + session binding |
| 4 · Platform Catalog | ADR-009 | capabilities/operations por domínio (source of truth) |
| 5 · North-Star | ADR-008 | discovery, federação, cost/rate policy (visão) |
| 6 · Control Plane | ADR-010, ADR-011, ADR-012, ADR-013, ADR-014 | catálogo/kinds, discovery, eventos, runtime, assets — plataforma como ecossistema |

Stack canônico (cliente → provider) — onde cada camada atua:

```
Clients
   │  Identity                          → ADR-003
   ▼  Token Exchange → Capability Token → ADR-004
   │  Transport: Streamable HTTP + session → ADR-006
   ▼  Platform Catalog: capability/operation discovery → ADR-009
   │  PEP                               → ADR-005
   ▼  PDP: scope/purpose/mandate/risk   → ADR-005 + ADR-007
   │  Runtime: planner → approval → executor (platform-devs-agent · repo standalone)
   ▼  Providers (MCP servers)
```

---

## Tese central (vale para todas as ADRs)

```
auth-mcp NÃO é um IdP permanente.
auth-mcp é STS / broker / borda OAuth interina.
platform-auth é o Authorization Server canônico — quando suportar OAuth 2.1.
O Twin Token é um Capability/Delegation Token efêmero (não um token de identidade).
```

---

## Diagnóstico compartilhado (evidências em `MCP_PARITY_PLATFORM_MARKETING.md` §9/§10)

- **`platform-governance` (DTR, mandatório):** PEP/PDP `TwinPep`/`GuardedToolRegistry` (lib
  `platform_governance` v1.0.2), transport-agnóstico; INV-1 (`assert_all_guarded`) no startup. **Valida**
  — não emite — um Twin Token. Traz HILT, purpose/LGPD, mandates, audit central.
- **`platform-auth` (IdP, mandatório):** emite tokens de usuário/serviço/agente; publica **JWKS RS256**.
  **NÃO tem OAuth 2.1/OIDC/PKCE/DCR** e **não emite Twin Token**.
- **`platform-admin` (mandatório):** ✅ **emissor canônico do Twin Token** (RS256, `kid=twin-signing-v1`,
  JWKS em `/api/v1/twin/jwks.json` = `URL_ADMIN_TWIN_JWKS`) + **Token Exchange RFC 8693** (`/twin/sessions`,
  `/twin/exchange`) + **federação de IdP** (`identity_federation`: `IDP_FEDERATION_CONFIG` por-tenant, SSO
  callback — **PKCE deferred**) + registro de twins/agentes. **Muita coisa do DTR JÁ ESTÁ LIGADA aqui.**
- **`platform-devs`:** já tem **Streamable HTTP nativo** (21 MCPs) — o **gap/vantagem real**. Também construiu
  borda OAuth (`auth-mcp`) + federação Keycloak, que se mostraram **redundantes** frente ao `platform-admin`.
- **`platform-marketing`:** 18 MCPs em **REST custom** (`http_sidecar`) + HMAC token; usa `platform-governance`.

**Conclusão (corrigida após analisar admin):** o DTR está **muito mais ligado do que parecia** — emissor,
token exchange e federação **já existem no `platform-admin`**. O que falta de fato: **transporte Streamable
HTTP** (temos), **adoção do PEP** nos MCPs (ninguém ativou), e a **superfície OAuth para o cliente MCP +
PKCE** (gap fino — ADR-004 D4.7). O `platform-devs` contribui o **transporte**; deve **consumir** (não
recriar) emissão/exchange/federação do admin+auth+governance.

---

## Arquitetura-alvo (fluxo canônico)

```
Cliente MCP (Claude Code/Desktop, Cursor, VS Code, Codex, ChatGPT, agentes próprios)
   │  OAuth 2.1 + PKCE (humano)  |  client_credentials/PAT (headless)      → ADR-003, ADR-006
   ▼
[AS canônico: platform-auth quando tiver OAuth  |  borda OAuth no auth-mcp-STS até lá]
   │  Access/Identity Token
   ▼
Token Exchange (RFC 8693) — auth-mcp-STS                                   → ADR-004
   │  Capability Token (Twin Token): efêmero, delegation (act/purpose/session)
   ▼
Service Discovery → MCP Session                                            → ADR-006, ADR-007, ADR-008
   ▼
PEP (platform_governance.TwinPep)  →  PDP (scope/purpose/mandate/HILT)      → ADR-005
   ▼
Audit  →  Tool Execution  →  Output Policy / Result Filter  →  Response     → ADR-005
```

---

## Decisão estratégica pendente (não trava a V1)

**Plataforma interna × produto comercial** → define quanto do **ADR-008** (north-star) vira prioridade.
E há uma decisão de plataforma dentro do ADR-004: **quem assina o Twin Token no fim** (platform-auth/
platform-admin), com o `auth-mcp-STS` como ponte interina **com sunset explícito**. Requer sign-off dos
donos de **platform-auth + platform-governance + platform-admin** e uma análise ainda pendente do
**`platform-admin`** (nó do JWKS do Twin Token).

## Próxima fase — Platform Control Plane (proposto, não-segurança)

A base de identidade/authz/transporte (003–007) + o catálogo (009) estão cobertos. **Recomendação: pausar
ADRs de segurança** (aprofundar OAuth/PEP/PDP gera sobreposição) e mover o foco para o **Control Plane** —
catálogo, descoberta, runtime, eventos e ativos. Bloco **escrito** (Status: Proposed) — ADR-010…014:

| ADR | Tema | Nota de escopo (evitar redundância) |
|---|---|---|
| ADR-010 | **Platform Catalog — meta-modelo de *kinds*** | o *kind system* do catálogo (estilo Backstage: Component/API/Resource/System). ⚠️ a ADR-009 já define o núcleo Capability/Operation/Tool/Provider/Resource → ADR-010 é o **meta-modelo geral**, não a redefinição desses. |
| ADR-011 | **Discovery** — versionamento, health, metadata, compat, search | tira o discovery do north-star (ADR-008) e o torna concreto/consumível. |
| ADR-012 | **Event Model** — eventos canônicos | `PlanCreated`, `PlanApproved`, `ExecutionStarted/Completed`, `PolicyDenied`, `CapabilityInvoked`, `RunbookCompleted`. Fecha auditoria/analytics/observabilidade; `dataforall-kafka` já existe. |
| ADR-013 | **Runtime** — Planner/Executor/Scheduler/Memory/Budget/Approval/Recovery/Retry | formaliza o que **já existe** no `platform-dev-agent` (hoje repo standalone `platform-devs-agent`, pacote `app/devs_agent`) como arquitetura descrita. |
| ADR-014 | **Asset Model** — ADRs/Prompts/Policies/Runbooks/Personas/Templates/Knowledge versionados | as **instâncias** de asset no catálogo. ⚠️ resolver sobreposição com ADR-010 (kinds) na escrita: 010 = tipos, 014 = instâncias. |

Horizonte: **Layer 6 · Control Plane** (ADR-010..014) — deixa de ser segurança e passa a ser arquitetura de
plataforma (operar, evoluir e escalar como ecossistema de engenharia).

---

## Origem
Esta divisão incorpora uma revisão externa de arquitetura (MCP/OAuth 2.1/Zero Trust/identidade
distribuída/multiagente) e as ressalvas de reconciliação com o estado real dos repositórios da plataforma.

---

## ADRs operacionais (fora desta série de segurança/capabilities)

Decisões de plataforma/engenharia que não pertencem às camadas de auth/capability acima, mas
ficam catalogadas aqui para não se perderem no histórico de commits:

| ADR | Tema |
|---|---|
| [ADR-001](ADR-001-PYTHON-POSTGRESQL-MIGRATION.md) | **Python + PostgreSQL** — migração do stack TS/SQLite; PostgreSQL como source of truth do fleet |
| [ADR-002](ADR-002-REPO-AUTOMATION-GOVERNANCE.md) | **Repo Automation & Governance** |
| [ADR-015](ADR-015-INFRA-PERSISTENCE-STRATEGY.md) | **Infra Persistence Strategy** — SQLite oficial para `infra`/`session` até haver PG concorrente-seguro; **emenda escopada** à ADR-001 (com critérios de migração) |
| [ADR-016](ADR-016-CI-VALIDATION-STRATEGY.md) | **CI Validation Strategy** — testes herméticos, venv limpo CI-faithful, plugins obrigatórios (`pytest-cov`/`pytest-asyncio`), cobertura ≥80%, `fail-fast: false`, reporte por contagem |
