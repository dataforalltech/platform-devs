# ADR-007 — Capability Model

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-004 (capability token/risk→TTL), ADR-005 (PDP consome), ADR-003 (workload identity), ADR-008 (registries)

## Context
A autorização precisa de um **modelo de capacidade** consistente: como uma ferramenta se mapeia a uma
capability, que escopo exige, qual seu risco, quem pode chamá-la e como isso se liga à sessão. Hoje o
`platform-devs` tem `SCOPE_FOR_TOOL` (bom, mas simples) e o `platform-governance` tem capabilities +
`policy_store`. Precisamos do contrato mínimo do modelo (o **registry** central é north-star — ADR-008).

## Decision

**D7.1 — Toda ferramenta declara um contrato de capability:**
```python
@mcp_tool(
    capability="crm.customer.read",   # <domínio>.<área>.<verbo> (namespacing consistente)
    required_scope="crm:read",         # escopo mínimo (deny-by-default)
    risk="low",                        # risk tier → TTL do token (ADR-004) e HILT (ADR-005)
    allowed_identities=("user","agent","svc"),  # quais classes podem chamar (ADR-003)
)
```

**D7.2 — Risk tiers (dirigem token TTL e HILT):**
| Tier | Exemplos | TTL do Twin Token (ADR-004) | HILT (ADR-005) |
|---|---|---|---|
| `low` | leitura/consulta | 30–60 s | não |
| `medium` | geração/escrita reversível | 30 s | não |
| `high` | mutação sensível / dados de outro tenant | single-use | opcional |
| `critical` | irreversível / infra / segredos / financeiro | single-use | **obrigatório** |

**D7.3 — `capability` vs `required_scope`:** a **capability** identifica a ação (unidade de política); o
**scope** é o direito que o token precisa carregar. O PDP casa `required_scope` ⊆ `scopes` do token **e**
avalia a capability contra policy/purpose/mandate. Deny-by-default.

**D7.4 — Workload identity no modelo (ADR-003).** Uma capability pode restringir **quais classes** a chamam
(`allowed_identities`). Ex.: `deploy.release.write` só para `svc:`/`agent:` sob mandato; nunca `wl:` genérico.

**D7.5 — Session binding (ADR-006).** Toda invocação carrega `session_id` (+ `conversation_id`, `workspace`,
`tenant`, `client`, `purpose`) — para auditoria, HILT contextual e tracing. O capability token (ADR-004)
inclui `session_id`.

**D7.6 — Namespacing por domínio.** `capability = <domínio>.<área>.<verbo>` (ex.: `security.scan.run`,
`crm.customer.read`). Alinha com o padrão do `platform-governance` e prepara o Capability Registry (ADR-008).

## Consequences
- **+** Modelo declarativo, consistente e escalável (melhor que ACL por ferramenta).
- **+** Risk tier unifica TTL de token + HILT + (futuro) rate/cost policy (ADR-008).
- **+** Session binding melhora auditoria/HILT/tracing.
- **−** Requer classificar risco e `allowed_identities` de **todas** as tools (esforço de curadoria).
- **−** Sem um Capability Registry central (ADR-008), o contrato vive espalhado nas tools (aceitável na V1).

## Open questions
- Taxonomia de capabilities por domínio (quem é dono de cada namespace?).
- Fonte da verdade do risk tier: no código da tool (V1) ou no registry (north-star)?
- Regras de quais `allowed_identities` para famílias de capabilities sensíveis.
