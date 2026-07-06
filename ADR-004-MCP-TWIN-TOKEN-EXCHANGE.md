# ADR-004 — Twin Token & Token Exchange (RFC 8693)

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-003 (identidade), ADR-005 (PEP valida o token), ADR-007 (capability/risk)

## Context
> **ATUALIZAÇÃO (análise do `platform-admin`, 2026-07-05):** a premissa "ninguém emite o Twin Token" estava
> ERRADA — olhamos o `platform-auth` (fino), não o `platform-admin` (rico). O **`platform-admin` já é o
> emissor canônico** e **já implementa Token Exchange (RFC 8693)**. Isto RESOLVE o D4.6 e reduz o papel do
> `auth-mcp`. Ver "Estado real da plataforma" abaixo.

O `platform-governance` (TwinPep) **valida** o Twin Token. A ADR monolítica o tratava quase como token
primário. **Correção (revisão de arquitetura):** o Twin Token é um **Capability/Delegation Token**, derivado
da identidade via **Token Exchange (RFC 8693)** — não um token de autenticação.

### Estado real da plataforma (evidência — `platform-admin`)
- **Emissor canônico = `platform-admin`.** Assina RS256, `kid=twin-signing-v1`, TTL 900s; JWKS em
  `/api/v1/twin/jwks.json` (= `URL_ADMIN_TWIN_JWKS` que o governance consome).
  Emissão: `POST /api/v1/twin/sessions` — recebe o **user JWT** (do `platform-auth`), valida contra o JWKS
  do auth, e minta o Twin Token com `iss=platform-admin/twin`, `sub=user:<id>`, `act={sub:agent_id,
  purpose_id, purpose_version, purpose_sig}`, `aud=[mcp:<svc>]`, `token_use=twin`, `scopes`, `twin_id`, `jti`.
- **Token Exchange (8693) = `POST /api/v1/twin/exchange`** (interno): front-door token (`aud=mcp:gateway`) →
  inner token por serviço (`aud=mcp:<svc>`), TTL 60s, `parent_jti` para revogação. Modelo DTR "C".
- **Registro de twins/agentes:** `TWIN_DEFINITION`, `TWIN_IDP_GROUP_SCOPE_MAP`, `TWIN_SESSION`.
- **Chaves separadas** por serviço (auth assina user token; admin assina twin token) — cada um com seu JWKS.

## Decision

**D4.1 — Três tokens, papéis distintos.**
```
Identity Token (OIDC-ish)   →   Access Token (OAuth)   →   Capability Token (Twin Token)
   "quem é o principal"          "o principal está         "este principal foi autorizado a
                                  autenticado"               executar ESTA capacidade agora"
```
O MCP **só aceita o Capability Token** (Twin Token). Identity/Access ficam na borda.

**D4.2 — Token Exchange (RFC 8693) é o mecanismo central.** O `auth-mcp-STS` (ADR-003) troca um
Access/Identity Token (ou service/agent token) por um **Twin Token** escopado a uma capability/recurso:
```
POST /oauth/token  (grant_type=urn:ietf:params:oauth:grant-type:token-exchange)
  subject_token=<access token do humano/agente>          # quem age
  actor_token=<opcional: token do serviço que delega>    # ator na cadeia
  resource=mcp:<serviço>                                  # RFC 8707
  scope=<capability/required_scope>
→ Twin Token (efêmero) para chamar aquele MCP.
```
Resolve delegação, impersonation controlada, service chaining e auditoria de cadeia.

**D4.3 — Twin Token é efêmero, por faixa de risco (não single-use universal).**
| Risk tier da capability (ADR-007) | TTL do Twin Token |
|---|---|
| read / baixo | 30–60 s |
| write / médio | 30 s |
| sensível / HILT / irreversível | **single-use** (1 chamada) |
Access Token permanece ~30 min; o Capability Token é curto porque representa **uma capacidade**, não identidade.

**D4.4 — Contrato do Twin Token (claims).** JWT RS256/EdDSA, `kid` obrigatório, e:
- `token_use: "twin"`, `aud: mcp:<serviço>` (RFC 8707), `iss` = emissor confiado (ver D4.6)
- `sub` (principal: `user:`/`agent:`/`svc:`/`wl:`), `tenant_id`
- **Delegação (8693):** `act` (`{sub: <ator>}`), `delegated_by`, `may_act` quando aplicável
- **`purpose_id`** (referência) — regras/validade **no PDP** (ADR-005), não no token
- **`session_id`**, `origin` (cliente/IP/workflow), `capability`, `scopes`
- `jti` (revogação), `iat`, `nbf`, `exp` (curto — D4.3)

**D4.5 — `purpose_id`: referência no token + regras no PDP.** O id fica no token (binding de auditoria e do
capability token); as **regras mutáveis** de purpose são resolvidas pelo PDP em tempo de decisão (ADR-005).
Não colocar a *definição* de purpose no JWT.

**D4.6 — Quem assina/emite. ✅ RESOLVIDO: `platform-admin`.**
- O `platform-admin` **já é** o emissor canônico (RS256, `kid=twin-signing-v1`) e **já faz Token Exchange
  (8693)** — ver "Estado real". **NÃO** criamos issuer no `auth-mcp` (a antiga "Opção A" está DESCARTADA:
  seria um segundo emissor redundante e trust sprawl desnecessário).
- **O `auth-mcp` NÃO assina nem emite Twin Token.** Todo Twin Token vem do `platform-admin`
  (`/twin/sessions` para o token de sessão; `/twin/exchange` para o inner token por serviço).
- **Alinhar nós ao contrato real:** os MCPs do `platform-devs` validam Twin Tokens do `platform-admin`
  (`iss=platform-admin/twin`, JWKS `URL_ADMIN_TWIN_JWKS`); nosso JWT bespoke (`aud=resource-url`) é aposentado.

**D4.7 — Gap remanescente: superfície OAuth 2.1 para o CLIENTE MCP (+ PKCE).** O que a plataforma NÃO tem é
o handshake OAuth que um cliente MCP arbitrário (Claude Code, Cursor…) espera: PRM → DCR → `/authorize`+
`/token`+**PKCE** para obter token **sem sessão web prévia**. O `platform-admin` faz **login SSO** (OIDC
client, browser→IdP→callback) mas com **PKCE deferred**, e não expõe um AS OAuth para clientes MCP. Opções:
- **(i) Completar no `platform-admin`/`platform-auth`:** adicionar AS OAuth (PRM/DCR/`/authorize`+PKCE/token)
  que, após o login, chama `/twin/sessions`. **Canônico** — preferível.
- **(ii) Ponte fina no `auth-mcp`:** front-door OAuth (PRM/DCR/PKCE) que autentica via platform-auth/admin e
  **troca** por Twin Token chamando `/twin/sessions` — **sem assinar nada**. Interim, com sunset.
Isto substitui a antiga decisão A/B/C: a emissão está decidida (admin); a discussão residual é só **onde mora
o front-door OAuth do cliente**.

## Consequences
- **+** Tokens de capacidade curtos + delegação = Zero Trust real, menor blast radius, auditoria de cadeia.
- **+** Token exchange é padrão (8693) → interopera com clientes/IdPs.
- **−** Mint por chamada em tiers sensíveis (latência) — mitigar com cache curto e single-use só onde importa.
- **−** Trust set com 2 issuers no interim (gerido por sunset + ADR-008 trust domains).

## Open questions
- ~~Análise do `platform-admin`~~ ✅ feita — emissor = `platform-admin` (D4.6 resolvido).
- **Onde mora o front-door OAuth do cliente MCP (D4.7)** — completar no `platform-admin`/`platform-auth`
  (canônico) ou ponte interina no `auth-mcp`? E **completar o PKCE** (hoje deferred no SSO do `platform-admin`).
- Claims/`purpose` do Twin Token para **humano** conectando um cliente MCP (o `act`/purpose foi desenhado
  para agente; para humano direto, qual `agent_id`/purpose?).
- TTL do inner token (60s) vs latência de re-exchange por chamada — medir.
