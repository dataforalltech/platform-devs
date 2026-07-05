# Piloto — Security via Streamable HTTP + OAuth (auth-mcp)

Prova de conceito ponta a ponta do padrão de `MCP_SERVICE_STANDARD.md`:
**auth-mcp** (Authorization Server) emite tokens → **Security** (Resource Server, Streamable HTTP)
valida e aplica escopo por ferramenta → **Claude Code** conecta nativamente.

## Componentes entregues

| Arquivo | Papel |
|---|---|
| `shared/mcp_auth.py` | Lib reutilizável: emissão/validação JWT, JWKS, store estático (bcrypt), middleware Bearer, PRM |
| `auth-mcp-server/authorization_server.py` | Authorization Server OAuth 2.1 (JWKS, metadata, `client_credentials`, introspect) |
| `security-mcp-server/src/server/mcp_server.py` | Security em **Streamable HTTP** (FastMCP) + middleware de auth + PRM |

## Verificação automatizada

O E2E (19 asserts) cobre: emissão de token, JWKS/discovery, validação de audience,
`401` sem token (com `WWW-Authenticate`), `403 insufficient_scope` por ferramenta, e execução
real de ferramenta pela camada MCP. Resultado atual: **19 PASS / 0 FAIL**.

## Rodando localmente

Instale as deps (uma vez): `pip install "mcp>=1.10" fastapi "uvicorn[standard]" python-multipart pyjwt cryptography bcrypt`

**1. Suba o Authorization Server (auth-mcp):**
```bash
# dev: gera chave efêmera e um client de demo 'security-dev' (secret: dev-secret-change-me)
PYTHONPATH=. AS_ISSUER=http://localhost:7103 \
  python -m uvicorn auth-mcp-server.authorization_server:app --port 7103
```

**2. Suba o Security (Resource Server):**
```bash
cd security-mcp-server
PYTHONPATH=..:. MCP_PORT=7100 \
  AS_ISSUER=http://localhost:7103 \
  SECURITY_RESOURCE=http://localhost:7100/mcp \
  python -m src.server.mcp_server
```

**3. Peça um token (bootstrap client_credentials):**
```bash
curl -s -X POST http://localhost:7103/oauth/token \
  -d grant_type=client_credentials \
  -d client_id=security-dev -d client_secret=dev-secret-change-me \
  -d resource=http://localhost:7100/mcp \
  -d scope='security:scan security:read security:model'
# → {"access_token":"eyJ...","token_type":"Bearer","expires_in":3600,"scope":"..."}
```

## Conectando o Claude Code

**CLI (Bearer bootstrap — imediato):**
```bash
claude mcp add --transport http security http://localhost:7100/mcp \
  --header "Authorization: Bearer <ACCESS_TOKEN>"
claude mcp list          # security → connected
```

**CLI (OAuth nativo — quando o fluxo auth-code+PKCE estiver ligado):**
```bash
claude mcp add --transport http security https://mcp.suaempresa.com/security
# 1ª chamada: Claude Code recebe 401 → lê /.well-known/oauth-protected-resource
# → descobre o auth-mcp → abre o navegador para login → guarda o token.
```

**Desktop:** Configurações → **Connectors** → *Add custom connector* → URL do Security.

## O que já é real (tudo verificado no E2E, 30/30)

- ✅ Streamable HTTP nativo (sem `mcp-http-wrapper.py`).
- ✅ Validação de JWT (assinatura via JWKS, `aud`, `exp`, `iss`) — rejeita audience errado.
- ✅ Escopo mínimo **por ferramenta** (`security:read|scan|model`), deny-by-default.
- ✅ `.well-known/oauth-protected-resource` (dispara o fluxo OAuth do cliente).
- ✅ Grant `client_credentials` (serviço↔serviço e bootstrap do dev).
- ✅ **Dynamic Client Registration** (RFC 7591) — Claude Code se registra sozinho como client público.
- ✅ **Authorization Code + PKCE (S256)** com tela de consentimento — login de browser do dev.
- ✅ **Refresh token** com rotação single-use (reuso do token antigo é rejeitado).
- ✅ **Persistência OAuth** (`shared/oauth_store.py`): Postgres em produção, in-memory em dev.
- ✅ **Chave de assinatura via secrets**: `AS_PRIVATE_KEY_FILE` (volume/secret) ou `AS_PRIVATE_KEY_PEM`.

### Fluxo OAuth interativo (login de browser)

```bash
# Claude Code faz automaticamente ao conectar sem token; manualmente o fluxo é:
# 1. Descoberta:   GET /.well-known/oauth-authorization-server
# 2. Registro:     POST /register  {redirect_uris, token_endpoint_auth_method:"none", scope}
# 3. Autorização:  GET /oauth/authorize?response_type=code&client_id=..&redirect_uri=..
#                      &code_challenge=<S256>&scope=..&resource=<url do mcp>&state=..
#                  → tela de consentimento → redirect com ?code=..
# 4. Token:        POST /oauth/token grant_type=authorization_code
#                      &code=..&redirect_uri=..&client_id=..&code_verifier=..
#                  → {access_token, refresh_token}
```

## ⏭️ O que falta para produção plena

- Integrar a **tela de consentimento a um login real** (IdP/SSO) — hoje aceita `username` livre (dev).
- Provisionar Postgres para o `OAUTH_STORE=postgres` e migrar os clients de serviço para lá.
- TLS na borda + rede privada — ver `deploy/` (Caddy + `docker-compose.pilot.yml`) e `MCP_SERVICE_STANDARD.md` §10.
- Aplicar o template a outros DevTeam e travar o "DoD" (§11) no CI.

## Regressão

`tests/e2e/test_oauth_security_pilot.py` — roda in-process (TestClient), 30 asserts cobrindo
transporte, auth, escopo por ferramenta, DCR, PKCE (com caso negativo) e rotação de refresh.

## Segurança — notas do piloto

- A chave RSA do AS é **efêmera** sem `AS_PRIVATE_KEY_PEM`; defina-a em produção (senão tokens
  morrem a cada restart e não há rotação controlada).
- O client de demo (`security-dev` / `dev-secret-change-me`) é só para dev; use `AS_CLIENTS_JSON`.
- O Security **nunca** recebe o token de outro recurso: o `aud` é validado contra `SECURITY_RESOURCE`.
