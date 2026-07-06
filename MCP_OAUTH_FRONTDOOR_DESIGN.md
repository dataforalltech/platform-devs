# Front-Door OAuth com Auto-Refresh — Claude Code Desktop → gateway `platform-mcp`

> **Decisão de arquitetura (fixada):** o **auth-mcp (AS)** faz toda a UX OAuth (DCR / PKCE / login / refresh). No `/token`, em vez de assinar o token próprio, o AS **chama `POST /api/v1/twin/sessions` no platform-admin e devolve o Twin Token (`aud=mcp:gateway`) como `access_token`** — a **PONTE**. O **gateway** apenas passa a **anunciar** o PRM (RFC 9728) e o header `WWW-Authenticate` apontando pro AS. **A verificação do Twin Token no gateway não muda.**

Isso é possível porque o Twin Token emitido pelo admin já satisfaz, letra por letra, o contrato que o `TwinTokenVerifier` exige (RS256/EdDSA, `kid` no JWKS de `URL_ADMIN_TWIN_JWKS`, `aud=mcp:gateway`, `token_use="twin"`, `exp`, `jti`, `sub`, `tenant_id`). Ou seja: o access_token que o Claude Code carrega **é** um Twin Token válido — o gateway não sabe (nem precisa saber) que veio de um fluxo OAuth.

---

## 1. Diagrama do fluxo completo

```
 Claude Code CLI/Desktop        gateway (platform-mcp)      AS (auth-mcp)           admin (platform-admin)
 ─────────────────────────      ──────────────────────      ─────────────           ──────────────────────
        │                              │                          │                          │
  (A) DISCOVERY                        │                          │                          │
        │ ── GET /mcp (sem token) ───► │                          │                          │
        │ ◄─ 401 + WWW-Authenticate: ─ │                          │                          │
        │     Bearer resource_metadata="https://GW/.well-known/oauth-protected-resource"     │
        │                              │                          │                          │
        │ ── GET /.well-known/oauth-protected-resource ─► GW       │                          │
        │ ◄─ {resource, authorization_servers:[AS_ISSUER], scopes_supported} ─ GW            │
        │                              │                          │                          │
        │ ── GET {AS}/.well-known/oauth-authorization-server ───────────────► │  (RFC 8414)  │
        │ ◄─ {authorization_endpoint, token_endpoint, registration_endpoint, jwks_uri, S256} │
        │                              │                          │                          │
  (B) DCR (RFC 7591)                   │                          │                          │
        │ ── POST {AS}/register ─────────────────────────────────► │                         │
        │ ◄─ {client_id: "dcr-…"} ───────────────────────────────  │                         │
        │                              │                          │                          │
  (C) PKCE + LOGIN + CONSENT           │                          │                          │
        │  gera code_verifier / code_challenge=S256                │                          │
        │ ── browser: GET {AS}/oauth/authorize?client_id&redirect_uri&code_challenge&         │
        │            code_challenge_method=S256&resource=https://GW&state&scope ─► │          │
        │ ◄─ tela login+consent ──────────────────────────────────  │                        │
        │ ── POST {AS}/oauth/authorize (user/senha) ──────────────► │ USER_STORE.verify()     │
        │ ◄─ 302 redirect ?code=…&state=&iss={AS} ─────────────────  │                        │
        │  valida iss == AS_ISSUER (RFC 9207)                       │                          │
        │                              │                          │                          │
  (D) TOKEN = PONTE p/ Twin Token      │                          │                          │
        │ ── POST {AS}/oauth/token ───────────────────────────────► │                        │
        │     grant=authorization_code, code, code_verifier,        │  _grant_authorization_code
        │     client_id, resource=https://GW                        │  valida PKCE S256       │
        │                              │                          │─ POST {ADMIN}/api/v1/twin/sessions ─►│
        │                              │                          │   Authorization: Bearer <user JWT>  │
        │                              │                          │   X-Tenant-Id, X-Internal-Token     │
        │                              │                          │   body {agentId, audiences:[mcp:gateway]}
        │                              │                          │◄─ {token: <TWIN JWT>, jti, expiresAt(15m)} ─│
        │ ◄─ {access_token: <TWIN JWT>, token_type: Bearer,        │                          │
        │     expires_in: 900, refresh_token: <AS opaco>, scope} ─  │                        │
        │  salva em ~/.claude/.credentials.json                     │                          │
        │                              │                          │                          │
  (E) USO NO GATEWAY                   │                          │                          │
        │ ── GET/POST /mcp  Authorization: Bearer <TWIN JWT> ─► GW  │                          │
        │     TwinTokenVerifier.verify() OK (aud=mcp:gateway,      │                          │
        │     token_use=twin, kid∈JWKS admin) → 200                │                          │
        │                              │                          │                          │
  (F) AUTO-REFRESH (a cada ~15 min)    │                          │                          │
        │  Twin exp em 900s → 401 no GW  OU  Date.now>exp-60s      │                          │
        │ ── POST {AS}/oauth/token ───────────────────────────────► │  _grant_refresh         │
        │     grant=refresh_token, refresh_token, client_id, resource│ take_refresh (rotaciona)│
        │                              │                          │─ POST {ADMIN}/api/v1/twin/sessions (re-mint) ─►│
        │                              │                          │◄─ novo TWIN JWT (15m) ──────────────│
        │ ◄─ {access_token: <novo TWIN>, refresh_token: <novo AS>} ─│                        │
        │  substitui credenciais, retoma chamadas ao GW            │                          │
```

**Ponto-chave do ciclo de vida:** o **refresh token do AS é a credencial de longa duração** (armazenada pelo Claude Code); o **Twin Token é de curta duração (~15 min)** e é re-mintado transparentemente a cada refresh. O Claude Code nunca vê nem gerencia o Twin Token diretamente como algo renovável — para ele é só um `access_token` Bearer opaco que expira.

---

## 2. Mudanças por repositório (concretas)

### 2.1 `platform-mcp` (gateway) — SÓ anunciar. Não muda verificação.

Duas mudanças: **(a)** rota pública de PRM, **(b)** header `WWW-Authenticate` nos 401. Mais **(c)** dois settings novos.

#### (a) Rota `/.well-known/oauth-protected-resource` (RFC 9728)

Hoje **não existe** nenhum handler `/.well-known/*` e todas as rotas são inline em `build_app()`. Adicionar **pública** (fora de `_require_twin_token`), no mesmo estilo dos health endpoints em `app/main.py:288-295`:

```python
# app/main.py — dentro de build_app(), junto dos health endpoints (~linha 295)
@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource():
    return {
        "resource": settings.GATEWAY_PUBLIC_URL,               # ex.: https://gateway.dataforall.…
        "authorization_servers": [settings.OAUTH_AS_ISSUER],   # ex.: https://auth.dataforall.…
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp:tools:read", "mcp:tools:execute"],
    }
```

> Nota RFC 9728: `authorization_servers` é um array de **issuer URLs** (strings), não de objetos com endpoints — o cliente descobre os endpoints via RFC 8414 no próprio AS. (O exemplo em prosa da evidência que aninhava endpoints está incorreto quanto ao shape; a forma correta é a acima.)

O CSP `default-src 'none'` do `SecurityHeadersMiddleware` **não** bloqueia resposta JSON, então nada muda ali para servir o metadata.

#### (b) Header `WWW-Authenticate` em TODO 401 do front-door

Hoje há 4 pontos de 401 e **nenhum** emite header. O caminho mais limpo e uniforme é **centralizar no `SecurityHeadersMiddleware`** (`app/core/security_headers.py`), que já roda em toda resposta com `setdefault`. Injetar o header quando o status for 401:

```python
# app/core/security_headers.py — dentro do dispatch/call do middleware, após obter `response`
if response.status_code == 401:
    response.headers.setdefault(
        "WWW-Authenticate",
        f'Bearer resource_metadata="{settings.GATEWAY_PUBLIC_URL}/.well-known/oauth-protected-resource"',
    )
```

Isso cobre de uma vez os 401 de `_require_twin_token` (`main.py:109/114/119`), o SSE `GET /mcp` (`main.py:613/617`) **e** os `JSONResponse` do Streamable `POST /mcp` (`main.py:517-539`) — sem tocar em cada rota. (Alternativa, se preferir explícito por rota: passar `headers={...}` em cada `HTTPException`/`JSONResponse`, com um helper `_www_authenticate()` compartilhado.)

#### (c) Novos settings em `app/core/config.py`

```python
# app/core/config.py — junto de GATEWAY_AUDIENCE (linha 23) / URL_ADMIN_TWIN_JWKS (linha 26)
GATEWAY_PUBLIC_URL: str = "https://gateway.local"     # URL pública do resource (o próprio gateway)
OAUTH_AS_ISSUER: str = "http://localhost:7103"        # issuer do auth-mcp (AS_ISSUER do AS)
```

**Isso é tudo no gateway.** `TwinTokenVerifier`, `GATEWAY_AUDIENCE`, `URL_ADMIN_TWIN_JWKS`, PEP, gates — **intocados**. O gateway continua aceitando exatamente o mesmo Twin Token de sempre; só passou a dizer *onde* obtê-lo.

---

### 2.2 `auth-mcp` (AS) — a PONTE no `/token` e no refresh

O único gargalo de emissão de access token é `_mint_access(...)` em `authorization_server.py:178-184`, chamado pelos 3 grants (`authorization_code` l.484, `refresh_token` l.503, `client_credentials` l.526). É aí que embrulhamos.

#### Estratégia: substituir a mintagem local por uma chamada ao admin

Em vez de `issue_jwt(...)` (assinar token próprio do AS), `_mint_access` passa a chamar `POST {ADMIN}/api/v1/twin/sessions` e devolver o Twin Token. Usar o `shared/twin_client.py` (já existe no repo).

```python
# authorization_server.py — substitui o corpo de _mint_access (l.178-184)
from shared.twin_client import mint_twin_session  # cliente para o platform-admin

def _mint_access(subject: str, resource: str, scopes: list[str], tenant_id: str,
                 client_id: str, role: str = "user") -> str:
    # subject vem como "user:alice" / "oidc:<sub>"; precisamos do user JWT da plataforma
    # e do agent_id resolvidos a partir do subject autenticado (ver mapeamento abaixo).
    platform_user_jwt = _resolve_platform_user_jwt(subject, tenant_id)   # NOVO
    agent_id          = _resolve_agent_for_client(client_id, scopes)     # NOVO
    resp = mint_twin_session(
        admin_base_url=ADMIN_BASE_URL,
        user_jwt=platform_user_jwt,          # Authorization: Bearer <user JWT>
        tenant_id=tenant_id,                 # X-Tenant-Id
        internal_token=ADMIN_INTERNAL_TOKEN, # X-Internal-Token (per-tenant, do PLATFORMS)
        agent_id=agent_id,
        audiences=["mcp:gateway"],           # força aud aceito pelo gateway
    )
    return resp["token"]                     # <- Twin Token JWT (aud=mcp:gateway, token_use=twin)
```

Como `_mint_access` já é chamado pelos 3 grants, **o refresh (`_grant_refresh`, l.493-508) re-minta automaticamente**: ele valida/rotaciona o refresh token opaco do AS (`take_refresh`) e chama `_mint_access` de novo → novo Twin Token de 15 min. Nenhuma mudança extra no fluxo de refresh além de garantir que os dados necessários (subject, tenant, agent) estejam persistidos com o refresh token.

#### Ajuste do corpo de resposta do `/token`

Os grants montam `{"access_token": access, "expires_in": DEFAULT_TTL, ...}` inline (l.487, l.505, l.527). Como o Twin Token tem TTL diferente (900s do admin, não `DEFAULT_TTL` do AS), `expires_in` deve refletir o TTL real do Twin — pegar de `expiresAt` da resposta do admin:

```python
# em cada grant, ao montar o body:
expires_in = _seconds_until(resp["expiresAt"])   # ~900, do admin — NÃO DEFAULT_TTL
body = {"access_token": access, "token_type": "Bearer", "expires_in": expires_in, "scope": " ".join(scopes)}
```

Isso é o que dispara o auto-refresh do Claude Code no tempo certo (`Date.now() > expires_at - 60s`).

#### Persistir o que o refresh precisa

Como o admin **força `user_id = sub do JWT`** (guard confused-deputy) e **não impersona via body**, o AS precisa, no refresh, reapresentar um user JWT válido daquele mesmo subject. Duas opções:

- **(preferida) Guardar junto ao refresh token:** `subject`, `tenant_id`, `agent_id`, e um meio de re-obter o user JWT da plataforma (ver riscos). O `oauth_store` já persiste dados de emissão do refresh — estender o registro com esses campos.
- **Alternativa:** o AS mantém sessão de usuário própria e reautentica silenciosamente para obter o user JWT no refresh.

#### Discovery: manter `oauth-authorization-server`, apontar `resource`

O AS **já serve** `/.well-known/oauth-authorization-server` (l.202-216) com `authorization_endpoint`, `token_endpoint`, `registration_endpoint`, `jwks_uri`, `S256`, `authorization_code`+`refresh_token`. **Nada a mudar aqui** — só garantir que o `resource` que o Claude Code envia (`https://GW`) seja aceito/validado e propagado. O `resource` do cliente vira o `aud` do token OAuth normal — mas na PONTE o `aud` real é `mcp:gateway` (do Twin). Decisão: manter validação de `resource` para binding de sessão/PKCE, mas o `aud` efetivo do access_token é o do Twin. Documentar essa divergência (o gateway valida `aud=mcp:gateway`, não a URL do resource).

---

### 2.3 `platform-admin` — pouca ou nenhuma mudança

O endpoint `POST /api/v1/twin/sessions` **já suporta** exatamente o padrão S2S que o AS precisa:

- Aceita `X-Internal-Token` (per-tenant, validado contra `PLATFORMS`) + `X-Tenant-Id` → `InternalTokenMiddleware`.
- Ainda exige `Authorization: Bearer <user JWT da plataforma>` — o handler chama `_verified_claims` incondicionalmente e deriva `user_id` do `sub` verificado (`routers.py:113-125`).
- `audiences=["mcp:gateway"]` no body → força o `aud` que o gateway exige (senão seria derivado das capabilities do purpose).
- TTL do Twin Token = `TWIN_TOKEN_TTL_SECONDS` (default **900s**), configurável em `config.py:242`.

**O que precisa existir/mudar:**

1. **Par `X-Internal-Token` per-tenant para o AS.** Registrar o auth-mcp como plataforma interna em `ADMIN_DATAFORALL.PLATFORMS` para cada tenant que fará login. Sem isso o `InternalTokenMiddleware` rejeita com 401 `invalid_internal_token`. (Config/provisionamento, não código.)
2. **User JWT da plataforma.** O admin **não** aceita identidade "confiada" só pelo internal token — ele re-verifica um user JWT (`decode_token`, `audience=JWT_AUDIENCE`, `sub` numérico). Portanto o AS **precisa** apresentar um user JWT válido do usuário. **Decisão de design aberta** (ver §4): ou o AS obtém esse JWT da própria plataforma no login, ou se afrouxa o admin para confiar em `internal_service_verified` + subject fornecido. **Recomendação:** *não* afrouxar o admin (mantém o guard confused-deputy IAM-001); em vez disso o AS obtém o user JWT no login.
3. **TTL:** manter 900s. Não há refresh no admin (nem precisa) — o refresh vive no AS, que re-chama `/sessions`. Confirmado: **não existe rota de refresh/reissue do Twin Token** no admin; o padrão é re-mintar. Isso está alinhado.

**Resumo:** admin idealmente **não muda código** — só provisionamento (internal token do AS por tenant). A única mudança de código *possível* seria afrouxar o guard para aceitar `user_id` fornecido pelo serviço quando `internal_service_verified=True` — mas isso **não é recomendado** (reduz a garantia anti-impersonação).

---

## 3. Tratamento do TTL curto (~15 min)

O Twin Token vive **900s**. O Claude Code já implementa auto-refresh baseado em `expires_at`:

1. AS retorna `expires_in ≈ 900` (derivado do `expiresAt` do admin) no `/token`. Claude Code grava `expires_at = now + 900` em `~/.claude/.credentials.json`.
2. Quando `Date.now() > expires_at - 60s` **ou** o gateway devolve 401 (Twin expirado), o Claude Code dispara `POST {AS}/oauth/token` com `grant_type=refresh_token`.
3. `_grant_refresh` no AS: valida+rotaciona o refresh opaco → chama `_mint_access` → **novo Twin Token de 900s** + **novo refresh token** (rotação single-use). Body reflete o novo `expires_in`.
4. Claude Code substitui as credenciais e retoma as chamadas ao gateway. **Transparente** — o usuário não reautentica.

**Consequência:** o refresh token do AS deve ter TTL longo (dias/semanas) e sobreviver a restarts do CLI. O Twin Token de 15 min é puramente efêmero.

**Gaps conhecidos do cliente a mitigar no AS:**
- Claude Code (v2.1.136) às vezes **não persiste o `client_id` da DCR** entre restarts → o AS deve tolerar múltiplos registros DCR do mesmo cliente (idempotência por `redirect_uri`/`client_name`, ou aceitar re-registro barato). O `/register` atual já gera `client_id` novo a cada chamada — aceitável, mas gera lixo; considerar dedupe.
- Se o cliente **perder o refresh token**, cai de volta no fluxo interativo (login) — comportamento aceitável.
- **Rotação de refresh:** como o AS rotaciona o refresh (single-use), se uma resposta se perder na rede o cliente pode ficar com refresh inválido → forçar re-login. Aceitável no walking skeleton; endurecer depois (grace window).

---

## 4. Riscos / decisões abertas

| # | Tema | Risco / questão | Recomendação |
|---|------|-----------------|--------------|
| R1 | **User → user JWT da plataforma** | O admin exige `Authorization: Bearer <user JWT>` com `sub` numérico e `aud=JWT_AUDIENCE`. Como o AS obtém esse JWT após o login OAuth? O AS autentica via `USER_STORE.verify(user/senha)`, que **não** é necessariamente a plataforma. | O AS deve, no login, **trocar as credenciais por um user JWT da plataforma** (ex.: chamar o login da plataforma, ou emitir/obter um JWT com `sub` = user_id numérico da plataforma). Mapear identidade do AS ↔ user_id da plataforma é pré-requisito. |
| R2 | **User → agent_id** | `/twin/sessions` exige `agentId` de um agente **aprovado** com purpose assinado válido. Qual agente representa "Claude Code Desktop"? | Definir **um agente dedicado** "claude-code-desktop" (aprovado, purpose com capability de namespace `gateway` **ou** passar `audiences=["mcp:gateway"]` explícito). Mapear `client_id` da DCR → `agent_id`. Começar com um agente fixo único. |
| R3 | **Tenant** | O tenant precisa vir consistente em 3 lugares: `X-Tenant-Id`, claim do user JWT (cross-check no `TenantUUIDMiddleware`, mismatch→403), e o tenant do internal token. | O AS resolve tenant no login (do usuário) e propaga o **mesmo** valor nos 3. Erros de tenant são a principal fonte de 401/403 silenciosos. |
| R4 | **Internal token no AS** | O AS passa a deter um `X-Internal-Token` per-tenant de alto privilégio (mina Twin Tokens para usuários). Vazamento = mintar tokens para qualquer usuário **desde que** possua o user JWT correspondente (guard limita o dano a "o dono do JWT"). | Guardar o internal token em secret store (`config-mcp`/vault), nunca em código/log. O guard confused-deputy do admin já limita impersonação — **não afrouxar**. |
| R5 | **Segurança do refresh** | Refresh do AS é a credencial de longa duração no disco do cliente. Rotação single-use pode causar lockout em falha de rede. | Rotação com **grace window** curta (aceitar refresh anterior por N segundos após rotação) para tolerância a retry. Escopo `offline_access` obrigatório para emitir refresh (já é o comportamento do AS). |
| R6 | **`resource` vs `aud`** | O cliente envia `resource=https://GW`; o token OAuth normal usaria isso como `aud`. Na PONTE o `aud` real é `mcp:gateway`. | Documentar. Gateway valida `aud=mcp:gateway` (não a URL). O `resource` serve para binding de PKCE/sessão e para o discovery apontar ao gateway certo. Aceitável. |
| R7 | **PRM shape** | Anúncio incorreto de `authorization_servers` (objetos com endpoints vs. array de issuer strings) quebra o discovery do cliente. | Usar **array de issuer URLs** (RFC 9728) — cliente resolve endpoints via RFC 8414 no AS. |
| R8 | **jti / revogação** | O admin persiste a sessão por `jti`; revogar a sessão mata o Twin. Refresh cria **novo** `jti`. | Revogação de refresh no AS deve, idealmente, revogar a sessão admin correspondente (ligar `refresh → jti`). Fora do walking skeleton. |

---

## 5. Ordem de implementação mínima (walking skeleton)

Objetivo: **um login + um refresh funcionando end-to-end**, com o mínimo de partes móveis.

**Fase 0 — Provisionamento (sem código)**
1. Registrar o auth-mcp como plataforma interna no admin (`PLATFORMS`) para **um** tenant de teste → obter `X-Internal-Token` per-tenant.
2. Criar **um** agente `claude-code-desktop` **aprovado**, com purpose assinado válido, e um twin **ativo** para o usuário de teste.
3. Garantir que o usuário de teste tem um user JWT da plataforma obtível (para R1).

**Fase 1 — Gateway anuncia (isolado, testável sozinho)**
4. `config.py`: adicionar `GATEWAY_PUBLIC_URL`, `OAUTH_AS_ISSUER`.
5. `main.py`: rota pública `/.well-known/oauth-protected-resource`.
6. `security_headers.py`: `WWW-Authenticate` em respostas 401.
7. **Teste:** `GET /mcp` sem token → 401 com header correto; `GET /.well-known/oauth-protected-resource` → JSON válido. *(Verificação do Twin Token continua idêntica — regressão zero.)*

**Fase 2 — PONTE no AS, só authorization_code (sem refresh ainda)**
8. `shared/twin_client.py`: função `mint_twin_session(...)` (POST `/api/v1/twin/sessions` com os 3 headers + body `{agentId, audiences:["mcp:gateway"]}`).
9. `_resolve_platform_user_jwt(subject, tenant)` + `_resolve_agent_for_client(...)` (hardcode do agente fixo `claude-code-desktop` no início).
10. Substituir corpo de `_mint_access` (l.178-184) pela chamada à PONTE; ajustar `expires_in` no body do grant `authorization_code` (l.484-490).
11. **Teste manual:** rodar o discovery→DCR→PKCE→token no Claude Code; confirmar que o `access_token` retornado é um Twin JWT (`token_use=twin`, `aud=mcp:gateway`) e que `GET /mcp` no gateway retorna 200.

**Fase 3 — Refresh transparente**
12. Persistir `subject`, `tenant_id`, `agent_id` (e meio de re-obter o user JWT) junto ao refresh token no `oauth_store`.
13. Confirmar que `_grant_refresh` (l.493-508) → `_mint_access` re-minta o Twin (já é o caminho, dado que `_mint_access` é o gargalo comum). Ajustar `expires_in` no body do refresh (l.503-505).
14. **Teste:** esperar 15 min (ou forçar `expires_at` no passado); confirmar que o Claude Code faz `grant_type=refresh_token` e recebe **novo** Twin sem reautenticar; `GET /mcp` volta a 200.

**Fase 4 — Endurecimento (pós-skeleton)**
15. Mapeamento `client_id`↔`agent_id` real; grace window de rotação de refresh (R5); ligação `refresh→jti` para revogação (R8); dedupe de DCR (R e gap do cliente); mover internal token para secret store (R4).

---

### Referência de âncoras de código (arquivo:linha)

| Repo | Arquivo:linha | O quê |
|------|---------------|-------|
| platform-mcp | `app/main.py:288-295` | padrão de rota pública → adicionar PRM aqui |
| platform-mcp | `app/main.py:109,114,119,517-539,613,617` | pontos de 401 hoje sem header |
| platform-mcp | `app/core/security_headers.py` | injetar `WWW-Authenticate` em 401 (ponto central) |
| platform-mcp | `app/core/config.py:23,26` | vizinhança dos settings novos |
| auth-mcp | `authorization_server.py:178-184` | `_mint_access` → **ponto da PONTE** |
| auth-mcp | `authorization_server.py:484,503,526` | os 3 grants que chamam `_mint_access` |
| auth-mcp | `authorization_server.py:202-216` | `/.well-known/oauth-authorization-server` (já OK) |
| auth-mcp | `shared/mcp_auth.py:65-90` | `issue_jwt` (mintagem local que a PONTE substitui) |
| auth-mcp | `shared/twin_client.py` | cliente para o admin (já existe) |
| platform-admin | `app/modules/twin_session/routers.py:102-125` | `POST /twin/sessions` + guard confused-deputy |
| platform-admin | `app/modules/twin_session/services.py:45-102` | validações + `_derive_audiences` + mint |
| platform-admin | `app/core/config.py:241-242` | `TWIN_TOKEN_TTL_SECONDS=900` (TTL do Twin) |
| platform-admin | `app/main.py:678-712` | `InternalTokenMiddleware` (S2S) |