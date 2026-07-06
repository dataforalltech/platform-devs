# ADR-005 — Autorização MCP: PEP / PDP / Output Policy

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-004 (token validado aqui), ADR-007 (capability/risk), ADR-003 (identidade)

## Context
Autorização precisa ser **mandatória**, **por ferramenta** e **na entrada e na saída**. A plataforma já tem
o padrão: `platform_governance` (PEP/PDP, HILT, purpose, mandates, policy store). O `platform-devs` construiu
autz **bespoke** (`BearerAuthMiddleware` + `SCOPE_FOR_TOOL`) que **duplica** esse padrão.

## Decision

**D5.1 — PEP único mandatório = `platform_governance`.** Todo MCP enforça via `TwinPep`/`GuardedToolRegistry`.
O `platform-devs` **aposenta** `BearerAuthMiddleware`/`SCOPE_FOR_TOOL` como implementação de autz; o mapa
`SCOPE_FOR_TOOL` vira **input** (`capability` + `required_scope`) da registração no PEP.

**D5.2 — Invariante INV-1 no startup.** `assert_all_guarded(registry)` — toda tool governada só é alcançável
via PEP; o processo falha ao subir se alguma tool escapar. (É o gate estrutural do governance; entra no nosso
"Definition of Done".)

**D5.3 — Pipeline de autorização completo (entrada E saída):**
```
Tool call
  → PEP.enforce(capability, required_scope)          # valida Twin Token (ADR-004)
  → PDP: IdentityGate (revogação/jti) · ScopePurposeGate (scope + purpose_id→lookup)
          · MandateGate · HiltGate (aprovação humana → 409 Approval Required)
  → Audit (evento de decisão)
  → Tool Execution
  → Output Policy / Result Filter                     # NOVO: autoriza/filtra a RESPOSTA
  → Response
```

**D5.4 — Output Policy / Result Filter (nova exigência da revisão).** Nem só a chamada é autorizada — a
**resposta** também. MCPs com saída sensível (PII, segredos, dados de outro tenant) passam por um filtro de
saída: mascaramento/redação/negação por policy. Reaproveitar o que já temos (ex.: `scan_secrets`/masking do
Security) como implementação de referência do filtro.

**D5.5 — `purpose_id` resolvido no PDP.** O token carrega a referência (ADR-004 D4.5); as **regras** de
purpose (mutáveis, LGPD) são avaliadas no PDP em tempo de decisão via `policy_store`.

**D5.6 — HILT (Human-in-the-loop) de 1ª classe.** Capabilities sensíveis (risk tier alto, ADR-007) acionam
`enforce_or_park` → `ApprovalRequired` (409) com `approvalUid`/`checkpointUid`; o MCP não executa até aprovação.

**D5.7 — PEP invisível ao desenvolvedor (DX).** A tool declara só a intenção; o framework injeta o resto:
```python
@mcp_tool(capability="crm.customer.read", required_scope="crm:read", risk="low")
async def get_customer(customer_id: str): ...
# o decorator/registry cuida de enforce → PDP → audit → output policy
```

## Consequences
- **+** Um só motor de autz na plataforma (governance); HILT/purpose/LGPD/mandates "de graça".
- **+** Autorização de saída fecha o vazamento pós-execução.
- **+** DX declarativa reduz erro humano (não dá para "esquecer" o PEP — INV-1).
- **−** `platform-devs` reescreve a camada de autz (esforço médio; transporte e tools ficam).
- **−** Output policy adiciona latência em respostas grandes — aplicar por risk tier/tipo de dado.

## Open questions
- Contrato do Output Policy (declarativo por capability? por tipo de dado? por tenant?).
- Como o PDP diferencia risco por classe de identidade (`user:` vs `agent:` vs `wl:`) — ver ADR-007.
- Latência do PDP online vs decisão local em cache (governance é in-process; medir).
