# Keycloak — federação SSO do auth-mcp

Este diretório deixa a federação OIDC via **Keycloak** pronta: um realm importável para dev
(que serve de molde para produção) e o recorte de `.env` correspondente
(`deploy/.env.keycloak.example`).

O que o realm `mcp` já traz:
- **Client** `mcp-auth-mcp` (confidential, Authorization Code + PKCE S256), com o callback do
  auth-mcp em *Valid redirect URIs* (prod e dev).
- **Realm roles** `mcp-admins` e `mcp-devs`, expostas no id_token em `realm_access.roles`
  (mapper já configurado) — casa com `AS_UPSTREAM_OIDC_ROLE_CLAIM=realm_access.roles`.
- **Usuários demo**: `alice`/`alice` (mcp-admins → role `admin`) e `bob`/`bob` (mcp-devs → `developer`).

---

## A) Testar o fluxo federado REAL localmente

Isto exercita a única parte que os testes automatizados não cobrem: o HTTP real ao IdP.

```bash
# 1. sobe o Keycloak de dev (realm importado no boot)
docker compose -f deploy/keycloak/docker-compose.keycloak.yml up -d
#    admin console: http://localhost:8081  (admin/admin)

# 2. rode o auth-mcp apontando para o Keycloak (bloco DEV do .env.keycloak.example)
export AS_ISSUER=http://localhost:7103
export AS_UPSTREAM_OIDC_ISSUER=http://localhost:8081/realms/mcp
export AS_UPSTREAM_OIDC_CLIENT_ID=mcp-auth-mcp
export AS_UPSTREAM_OIDC_CLIENT_SECRET=dev-mcp-client-secret
export AS_UPSTREAM_OIDC_REDIRECT_URI=http://localhost:7103/oauth/sso/callback
export AS_UPSTREAM_OIDC_ROLE_CLAIM=realm_access.roles
export AS_UPSTREAM_OIDC_ROLE_MAP='{"mcp-admins":"admin","mcp-devs":"developer"}'
PYTHONPATH=. python -m uvicorn auth-mcp-server.authorization_server:app --port 7103

# 3. rode o Security (outro terminal), como em security-mcp-server/PILOT.md
```

Agora dispare o fluxo (o Claude Code faz isso sozinho; manualmente, abra no browser):
`http://localhost:7103/oauth/authorize?response_type=code&client_id=<dcr>&redirect_uri=<cb>&code_challenge=<S256>&scope=openid%20security:scan&resource=http://localhost:7100/mcp&state=x`
→ clique **"Entrar via SSO (Keycloak)"** → login `alice`/`alice` no Keycloak → volta ao callback →
o auth-mcp emite o code. O token final terá `sub=oidc:<uuid-do-keycloak>` e `role=admin`.

Derrube com `docker compose -f deploy/keycloak/docker-compose.keycloak.yml down -v`.

---

## B) Produção

1. No **seu** Keycloak, importe/replique o realm (ou só o client) do `realm-mcp.json`:
   - Admin Console → Realm → Clients → *Import client* (ou Realm → *Partial import*).
   - **Troque o secret**: Clients → mcp-auth-mcp → Credentials → *Regenerate* (não use o de dev).
   - Ajuste *Valid redirect URIs* para o seu host público: `https://<seu-host>/auth/oauth/sso/callback`.
   - Confira que o mapper "realm roles (id token)" está com *Add to ID token* = ON.
   - Crie/associe as roles `mcp-admins`/`mcp-devs` aos grupos/usuários reais (ou ajuste o
     `AS_UPSTREAM_OIDC_ROLE_MAP` para as roles que você já usa).
2. Preencha o `.env` a partir de `deploy/.env.keycloak.example` (bloco de produção):
   - `AS_UPSTREAM_OIDC_ISSUER=https://<KC_HOST>/realms/<REALM>`
   - `AS_UPSTREAM_OIDC_CLIENT_ID=mcp-auth-mcp`
   - `AS_UPSTREAM_OIDC_CLIENT_SECRET` → **via secrets manager**, nunca no git.
   - `AS_UPSTREAM_OIDC_REDIRECT_URI=https://<seu-host>/auth/oauth/sso/callback`
3. Suba o stack (`docker-compose.pilot.yml`) — o botão "Entrar via SSO" aparece automaticamente
   quando `AS_UPSTREAM_OIDC_ISSUER` + `CLIENT_ID` estão setados.

## Notas
- O auth-mcp usa **Authorization Code + PKCE + nonce + state**; o client no Keycloak já vem com
  `pkce.code.challenge.method=S256`.
- Se `realm_access.roles` não aparecer no id_token, verifique o mapper (Add to ID token = ON) —
  é o ponto de ajuste mais comum entre versões do Keycloak.
- Só o auth-mcp fala com o Keycloak pela perna de backend (token/jwks); a autorização do usuário
  acontece no browser dele contra o Keycloak.
