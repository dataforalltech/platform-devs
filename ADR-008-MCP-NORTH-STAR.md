# ADR-008 — North-Star: Plataforma MCP de referência

**Status:** Proposed (North-Star, não-V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** 003–007 (a base V1 que isto estende)

## Context
As ADRs 003–007 definem a **base correta e executável agora** (V1). Esta ADR captura a **visão de plataforma
comercial/referência** — o que seria preciso para competir com Anthropic / OpenAI Enterprise / Azure AI
Foundry em governança de MCP multiagente. **A prioridade deste ADR depende da decisão estratégica
"plataforma interna × produto comercial"** (não trava a V1; a base 003–007 é a mesma nos dois casos).

## Decision (direção; itens são epics, não implementação imediata)

**N1 — Service Discovery de plataforma.** Além do PRM (auth) e do `tools/list` (protocolo), um catálogo
`/.well-known/mcp` (ou equivalente central) expondo: metadata, capabilities, autenticação, policies, health,
version. Substitui registros estáticos (ex.: `gateway_registry.json` do marketing) por descoberta dinâmica.

**N2 — Registries separados (estilo SPIFFE/control-plane):**
- **Capability Registry** (catálogo de capabilities + risk tier + donos)
- **Tool Registry** (tools → capability)
- **Resource Registry** (recursos/`aud` `mcp:<svc>`)
- **Policy Registry** (policies/purpose/mandates — hoje parcialmente no `platform_governance.policy_store`)
Fonte da verdade central, versionada, consultável.

**N3 — Trust Domains (capítulo próprio).** Formalizar: issuers, roots of trust, rotação de chaves,
cross-trust, federação, revogação. Necessário porque haverá múltiplos emissores (STS interino + platform-
auth/admin — ADR-004) e potencialmente múltiplos tenants/domínios. Define **quem confia em quem**.

**N4 — Cost / Budget / Rate Policy (governança além de autz).** Políticas de: tokens, requests, tool
invocations, execução paralela, **budget/custo** por tenant/agente/sessão. Crítico para multiagente (agentes
podem saturar ferramentas/custos). Estende o rate-limit atual do gateway (Redis) com dimensão de custo.

**N5 — Federação de identidade.** ⚠️ **Já existe** no `platform-admin` (`identity_federation`:
`IDP_FEDERATION_CONFIG` por-tenant + SSO callback OIDC). North-star aqui = **completar** (PKCE — hoje
deferred; state signing; mais provedores) e **consolidar** como o ponto único de federação. A federação
Keycloak/`oidc_upstream` do `platform-devs` é **redundante** e deve ser descontinuada em favor do admin.

**N6 — Roadmap commercial-grade.** Multi-tenant isolation forte, SLA/observabilidade por capability,
marketplace de MCPs/capabilities, billing por uso, certificação/DoD de terceiros.

## Consequences
- **+** Caminho claro de plataforma interna → produto de referência sem retrabalho da base (003–007 servem aos dois).
- **+** Registries + trust domains + discovery = operação em escala e para múltiplos consumidores/tenants.
- **−** Escopo grande: só faz sentido priorizar conforme a decisão estratégica; **não** é pré-requisito da V1.
- **−** Vários itens dependem de outros times (platform-auth/admin/governance) e de padronização cross-repo.

## Decisão que governa este ADR
**Plataforma interna** → N1–N6 entram sob demanda, incrementalmente sobre a V1.
**Produto comercial/referência** → N1 (discovery), N2 (registries), N3 (trust domains) e N4 (cost/rate) viram
prioridade alta logo após a V1; N5/N6 no roadmap de produto.

## Open questions
- A decisão estratégica interna×comercial (dono: liderança de plataforma).
- Quanto do N2 já é coberto pelo `platform_governance.policy_store` vs precisa de control-plane novo.
- Onde vive o control-plane de discovery/registries (novo serviço? extensão do governance/admin?).
