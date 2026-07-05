# ADR-006 — Transportes MCP

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-003 (identidade/clientes), ADR-005 (auth é ortogonal ao transporte)

## Context
Transporte é uma camada **independente** de identidade/autz. Os consumidores são **heterogêneos** (Claude
Code/Desktop, Cursor, VS Code, Codex, ChatGPT connectors, agentes próprios) com suportes diferentes de
transporte e versão de protocolo. Hoje: `platform-devs` = Streamable HTTP nativo; `platform-marketing` =
REST custom (`http_sidecar`); MCPs do `platform-auth` = REST custom + stdio.

## Decision

**D6.1 — Streamable HTTP nativo (SDK `mcp`) é o transporte padrão** de toda a plataforma (endpoint único
`/mcp`, JSON-RPC, resposta `application/json` ou SSE). Motivos: conexão nativa dos clientes MCP, melhor
reconnect/proxy/LB/observabilidade/tracing, e integra melhor com auth. `platform-marketing` e os MCPs do
`platform-auth` **migram** do REST custom para Streamable HTTP.

**D6.2 — Compatibilidade controlada (não default):**
- **SSE (HTTP+SSE legado):** suportado **apenas** como fallback para clientes que ainda não falam Streamable
  HTTP, atrás de flag, com data de descontinuação.
- **stdio:** para clientes/uso **local**; bind em `127.0.0.1` + validação de `Origin` (anti DNS-rebinding).

**D6.3 — Modo de sessão:** stateful por padrão (compat com clientes reais; `Mcp-Session-Id` não-determinístico,
≥128 bits, vinculado à identidade). `MCP_STATELESS=1` para escala horizontal com sticky sessions/event store.

**D6.4 — Requisitos transversais de borda:** validação de `Origin`/Host (allow-list), **CORS** nos endpoints
MCP e OAuth (clientes web/in-browser), TLS na borda, limites de payload/timeout por ferramenta.

**D6.5 — Matriz de compatibilidade de clientes (entregável obrigatório).** Manter e **testar por cliente**:
| Cliente | Transporte | Auth | Versão do protocolo | Status |
|---|---|---|---|---|
| Claude Code/Desktop | Streamable HTTP | OAuth/PKCE + Bearer | — | verificar |
| Cursor | Streamable HTTP / SSE? | OAuth? | — | verificar |
| VS Code (MCP) | Streamable HTTP | OAuth? | — | verificar |
| Codex | ? | ? | — | verificar |
| ChatGPT connectors | ? (modelo próprio) | OAuth (quirks) | — | verificar |
| Agentes próprios | Streamable HTTP | client_credentials/PAT | — | controlado |
> Não assumir comportamento — **confirmar e testar** cada um (quirks de `redirect_uri`/DCR/tools). É um
> gate de release: um cliente só é "oficialmente suportado" após passar na matriz.

## Consequences
- **+** Um transporte primário; clientes conectam nativamente; melhor operação.
- **+** Fallbacks controlados evitam excluir clientes legados sem virar dívida permanente.
- **−** `platform-marketing`/`platform-auth` precisam migrar do REST custom (esforço nos outros repos).
- **−** Manter SSE/stdio como compat tem custo — por isso flag + data de sunset.

## Open questions
- Quais clientes são **alvo oficial** da matriz (D6.5)?
- ChatGPT/OpenAI connectors exigem um perfil/adaptador específico?
- Precisamos de um gateway de borda único (Caddy/ingress) por serviço ou um multiplexador `/mcp/<serviço>`?
