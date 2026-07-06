# Conectando o auth-mcp a um IdP corporativo (OIDC)

O auth-mcp faz **federação OIDC upstream**: delega o login ao seu IdP e continua emitindo os
tokens dos recursos (Security/QA-Engineer). O código é genérico (Authorization Code + PKCE + nonce +
validação de id_token) — só muda a **configuração** por provedor.

## Passo comum (qualquer IdP)

1. **Registre uma aplicação** no IdP (tipo *Web/confidential*, Authorization Code).
2. **Redirect URI** = `https://<seu-host>/auth/oauth/sso/callback` (o path público via Caddy).
3. Habilite os scopes `openid email profile` (e o que expõe grupos/roles — ver abaixo).
4. Preencha as envs no `.env` (ver `deploy/.env.example`) e reinicie o `auth-mcp`.
5. Defina o mapeamento de grupos→role da plataforma via `AS_UPSTREAM_OIDC_ROLE_MAP`.

Envs base:
```
AS_UPSTREAM_OIDC_ISSUER=<issuer do provedor>
AS_UPSTREAM_OIDC_CLIENT_ID=<client id>
AS_UPSTREAM_OIDC_CLIENT_SECRET=<client secret — via secrets manager>
AS_UPSTREAM_OIDC_REDIRECT_URI=https://<seu-host>/auth/oauth/sso/callback
AS_UPSTREAM_OIDC_SCOPES=openid email profile
AS_UPSTREAM_OIDC_ROLE_CLAIM=<caminho do claim de grupos/roles>
AS_UPSTREAM_OIDC_ROLE_MAP={"<grupo-do-idp>":"admin","<outro>":"developer"}
AS_UPSTREAM_OIDC_DEFAULT_ROLE=developer
```

## Receitas por provedor

### Microsoft Entra ID (Azure AD)
- **Issuer:** `https://login.microsoftonline.com/<TENANT_ID>/v2.0`
- **Registro:** Azure Portal → App registrations → New registration → Web → Redirect URI acima.
  Crie um *client secret* em "Certificates & secrets".
- **Roles/grupos:** para roles de app use App Roles → claim `roles`; para grupos de diretório,
  habilite o *groups claim* no token → claim `groups` (vem como GUIDs, mapeie os GUIDs).
  - `AS_UPSTREAM_OIDC_ROLE_CLAIM=roles`  (ou `groups`)
- **Scopes:** `openid email profile` (grupos vêm por configuração do token, não por scope).

### Keycloak
- **Issuer:** `https://<host>/realms/<REALM>`
- **Registro:** Clients → Create → OpenID Connect → *confidential* (Client authentication ON) →
  Valid redirect URIs = o callback acima. Pegue o secret em Credentials.
- **Roles:** por padrão vêm em `realm_access.roles` (realm) ou `resource_access.<client>.roles`.
  - `AS_UPSTREAM_OIDC_ROLE_CLAIM=realm_access.roles`
- **Scopes:** `openid email profile`. (Se usar client scope de grupos, ajuste o claim.)

### Auth0
- **Issuer:** `https://<TENANT>.us.auth0.com/` (com a barra final; confira o `.well-known`)
- **Registro:** Applications → Regular Web Application → Allowed Callback URLs = o callback.
- **Roles:** Auth0 exige um *namespaced custom claim* (via Action/Rule), ex.:
  `https://suaempresa.com/roles`.
  - `AS_UPSTREAM_OIDC_ROLE_CLAIM=https://suaempresa.com/roles`
- **Scopes:** `openid email profile`.

### Google Workspace
- **Issuer:** `https://accounts.google.com`
- **Registro:** Google Cloud Console → Credentials → OAuth client ID → Web → Authorized redirect URIs.
- **Roles/grupos:** Google **não** emite grupos no id_token por padrão. Opções: mapear por domínio
  do e-mail (`hd` claim) e deixar todos no `AS_UPSTREAM_OIDC_DEFAULT_ROLE`, ou consultar a Directory
  API à parte (fora do escopo do hook atual).
  - `AS_UPSTREAM_OIDC_ROLE_CLAIM=` (vazio → todos recebem `DEFAULT_ROLE`)
- **Scopes:** `openid email profile`.

### Okta
- **Issuer:** `https://<org>.okta.com/oauth2/default` (ou o Authorization Server customizado)
- **Registro:** Applications → Create App Integration → OIDC Web → Sign-in redirect URI = callback.
- **Roles/grupos:** adicione um *groups claim* no Authorization Server → claim `groups`.
  - `AS_UPSTREAM_OIDC_ROLE_CLAIM=groups`
- **Scopes:** `openid email profile groups` (se o claim de grupos exigir o scope).

## Como validar depois de configurar

1. `docker compose -f docker-compose.pilot.yml up -d` com as envs no `.env`.
2. Abra `https://<seu-host>/auth/oauth/authorize?...` (ou deixe o Claude Code disparar o fluxo):
   a tela de consentimento deve mostrar **"Entrar via SSO (<nome>)"**.
3. Clique → você é levado ao IdP → após login, volta ao `/auth/oauth/sso/callback` → o auth-mcp
   emite o code e o Claude Code recebe o token.
4. Cheque o token (introspect ou decode): `sub` = `oidc:<subject-do-idp>`, `role` conforme o mapa.

## Segurança já implementada no hook

- PKCE S256 na perna auth-mcp→IdP; `nonce` no id_token (anti-replay); `state` anti-CSRF ligado à
  requisição original; validação de `iss`/`aud`/`exp`/assinatura (JWKS) do id_token; erro do IdP
  tratado (redirect com `error`); discovery cacheado. Ver `auth-mcp-server/oidc_upstream.py`.
- **Ainda depende de você:** registrar o app no IdP e injetar `CLIENT_SECRET` via secrets manager.
