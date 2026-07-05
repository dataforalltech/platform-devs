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

**Corte:** V1 = segurança correta e executável agora. North-Star = visão de plataforma comercial/referência.
A decisão estratégica **plataforma interna × produto comercial** afeta a **prioridade do ADR-008**,
**não** a arquitetura correta da base (003–007). Por isso a V1 não fica travada por essa decisão.

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

## Origem
Esta divisão incorpora uma revisão externa de arquitetura (MCP/OAuth 2.1/Zero Trust/identidade
distribuída/multiagente) e as ressalvas de reconciliação com o estado real dos repositórios da plataforma.
