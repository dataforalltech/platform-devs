# ADR-003 — Identidade MCP

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-004 (token exchange), ADR-006 (transporte), ADR-007 (capability), ADR-005 (PEP)

## Context
Os MCPs da plataforma são consumidos por **qualquer cliente MCP compatível** (Claude Code/Desktop, Cursor,
VS Code, Codex, ChatGPT connectors, agentes próprios) e por **workloads** (conectores, consumers, schedulers,
CI). O IdP mandatório `platform-auth` hoje **não tem OAuth 2.1** (só password login + service/agent token) e
**não federa** IdP externo. Precisamos definir as classes de identidade e onde a identidade é estabelecida —
sem criar dois IdPs.

## Decision

**D3.1 — Quatro classes de identidade (não duas).** SPIFFE-style; cada uma com `sub` distinto:

| Classe | `sub` | Como autentica | Exemplo |
|---|---|---|---|
| **Human** | `user:<id>` | OAuth 2.1 + PKCE (browser) | dev no Cursor/Claude Desktop/ChatGPT |
| **Agent** | `agent:<name>` | client_credentials / token de agente | agente autônomo, workflow multiagente |
| **Service** | `svc:<id>` | client_credentials (service token) | outro microserviço chamando um MCP |
| **Machine/Workload** | `wl:<id>` | client_credentials / workload identity | Kafka consumer, scheduler, CronJob, CI |

> Um Connector NÃO é um Agent; um CronJob NÃO é um Agent. Identidade própria por classe → autorização e
> auditoria corretas. `purpose`/risk podem diferir por classe (ver ADR-007).

**D3.2 — Um único Authorization Server canônico: `platform-auth`.** É onde a **identidade** é estabelecida.
Não criamos um segundo IdP.

**D3.3 — `auth-mcp` NÃO é emissor nem STS.** ⚠️ **Correção (análise do `platform-admin`):** o **STS/emissor
já existe** — o `platform-admin` emite o Twin Token e faz Token Exchange (RFC 8693) via `/twin/sessions` e
`/twin/exchange` (ver ADR-004). Portanto o `auth-mcp` **não** assina, **não** emite e **não** faz token
exchange. Seu único papel possível é uma **ponte fina de front-door OAuth** para o cliente MCP (PRM/DCR/PKCE)
que autentica via platform-auth/admin e **troca** por Twin Token chamando `/twin/sessions` — e mesmo isso é,
preferencialmente, completado dentro do `platform-admin`/`platform-auth` (ADR-004 D4.7). Interim → sunset.

**D3.4 — DCR obrigatório.** Não se pré-cadastra cada cliente/agente. Suportar public client
(`token_endpoint_auth_method=none` + PKCE) e confidential client.

**D3.5 — Dois fluxos de entrada, ambos 1ª classe:**
- **Interativo (humano):** OAuth browser → Access/Identity Token.
- **Headless (agent/service/workload):** client_credentials / **PAT/Bearer estático** (para clientes sem
  OAuth completo) → token de serviço/agente.

Ambos alimentam o **token exchange** (ADR-004) que produz o Capability Token que o MCP valida.

## Consequences
- **+** Modelo de identidade explícito e client-agnóstico; alinha com o modelo de agentes do DTR.
- **+** Single IdP evita trust sprawl; a borda interina desbloqueia o hoje.
- **−** Exige que `platform-auth` ganhe OAuth 2.1 para atingir o end-state (dependência de outro time).
- **−** Enquanto a borda for interina, há uma superfície OAuth fora do `platform-auth` (mitigado por sunset).

## Open questions
- `platform-auth` ganhará OAuth 2.1 nativo, ou a borda `auth-mcp` permanece como front-door OAuth oficial?
- Contrato de identidade para humano vs workload (claims mínimos por classe).
- Federação externa: ✅ **RESOLVIDO** — o lugar canônico é o **`platform-admin` (`identity_federation`)**:
  `IDP_FEDERATION_CONFIG` por-tenant + `/api/v1/sso/{tenant}/authorize` + `/sso/callback` (valida id_token de
  IdP externo, sincroniza scopes do twin por grupos). A **federação Keycloak/`oidc_upstream.py` do
  `platform-devs` é REDUNDANTE** — se Keycloak for usado, entra como IdP externo que o `platform-admin`
  federa. **Ressalva:** o SSO do `platform-admin` está com **PKCE deferred** (gap a completar — ADR-004 D4.7).
