# Deploy do Piloto MCP — Caddy (TLS) + rede privada

Guia para subir o piloto de `MCP_SERVICE_STANDARD.md` (§4, §10) num único host:
**Caddy** na borda (TLS automático) roteando por path para **auth-mcp** (Authorization
Server), **security-mcp** (Resource Server, Streamable HTTP) e **mcp-gateway**, todos
numa **rede privada**. Só o Caddy é público.

## Topologia (quem é público × quem é privado)

```
                 Internet / TLS 1.3
Claude Code ──HTTPS──▶  Caddy (público 80/443)
                          │  rede privada `mcp-private` (internal: true)
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                   ▼
  security-mcp:7100   auth-mcp:7103     mcp-gateway:8080
  (Resource Server)   (Authz Server)    (edge de política)
```

- **Só o Caddy publica portas** no host (`80:80`, `443:443`).
- **auth-mcp, security-mcp, mcp-gateway** só declaram `expose:` — visíveis apenas
  dentro da rede `mcp-private` (`internal: true`), sem porta no host e sem egress.
- O Caddy participa de **duas redes** (`edge` + `mcp-private`) e é a única ponte.

Roteamento por path (ver `deploy/Caddyfile`):

| Path público | Upstream interno | Observação |
|---|---|---|
| `https://<host>/security/mcp` | `security-mcp:7100/mcp` | endpoint MCP (Streamable HTTP) |
| `https://<host>/security/.well-known/oauth-protected-resource` | `security-mcp:7100/.well-known/...` | PRM (dispara OAuth no cliente) |
| `https://<host>/security/v1/health` | `security-mcp:7100/v1/health` | health público |
| `https://<host>/auth/.well-known/oauth-authorization-server` | `auth-mcp:7103/.well-known/...` | metadata do AS |
| `https://<host>/auth/.well-known/jwks.json` | `auth-mcp:7103/.well-known/jwks.json` | chaves públicas (JWKS) |
| `https://<host>/auth/oauth/token` | `auth-mcp:7103/oauth/token` | emissão de token |
| `https://<host>/auth/oauth/authorize` · `/introspect` · `/register` | `auth-mcp:7103/...` | fluxo OAuth |
| `https://<host>/gateway/*` | `mcp-gateway:8080/*` | gateway/registry |

O Caddy usa `handle_path`, que **remove o prefixo** (`/security`, `/auth`, `/gateway`)
antes de encaminhar — os apps registram suas rotas na raiz (ex.: `/mcp`, `/oauth/token`),
então o prefixo público não pode vazar para o upstream.

> **Por que os `.well-known` precisam bater exatamente:** o cliente OAuth do Claude Code,
> ao tomar `401`, lê `WWW-Authenticate` → busca o `SECURITY_PRM_URL` → lê o `issuer`
> (`AS_ISSUER`) → busca `.../.well-known/oauth-authorization-server` → daí o `jwks_uri`
> e o `token_endpoint`. Cada um desses é construído pelos apps a partir das variáveis de
> ambiente. Por isso `AS_ISSUER`, `SECURITY_RESOURCE` e `SECURITY_PRM_URL` (no `.env`)
> têm de usar **exatamente** o host/paths que o Caddy expõe.

## Pré-requisitos

- Docker + Docker Compose v2.
- Um domínio apontando (DNS A/AAAA) para o IP público do host — para o TLS via ACME.
  (Em dev local dá para pular o domínio e usar `tls internal`; ver adiante.)
- Portas `80` e `443` livres/abertas no host e no firewall (o ACME HTTP-01 usa a `80`).
- `openssl` e `python` (com `bcrypt`) na máquina onde você gera as credenciais.

## Passo a passo

### 1. Configure as variáveis

```bash
cp deploy/.env.example .env
# edite o .env: troque o domínio, gere a chave e os clients (abaixo).
```

Troque `mcp.suaempresa.com` pelo seu domínio **no `.env` e no `deploy/Caddyfile`**
(e o `email` do bloco global do Caddyfile).

### 2. Gere a chave RSA de assinatura do AS

```bash
openssl genpkey -algorithm RSA -pkcs8 -out as_key.pem -pkeyopt rsa_keygen_bits:2048

# passe o conteúdo para o ambiente (forma mais robusta p/ PEM multilinha):
export AS_PRIVATE_KEY_PEM="$(cat as_key.pem)"
```

Sem `AS_PRIVATE_KEY_PEM`, o AS usa uma chave **efêmera** (tokens morrem a cada
restart) — aceitável só em dev.

### 3. Gere o `AS_CLIENTS_JSON`

O secret do client vai como **hash bcrypt**, nunca em claro:

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'UM_SECRET_FORTE', bcrypt.gensalt()).decode())"
```

Monte o JSON (uma linha) no `.env`:

```
AS_CLIENTS_JSON={"security-ci":{"secret_hash":"$2b$12$...","subject":"svc:security-ci","scopes":["security:read","security:scan","security:model"],"tenant_id":"pilot"}}
```

### 4. Suba o stack

```bash
docker compose -f docker-compose.pilot.yml config    # valida a sintaxe
docker compose -f docker-compose.pilot.yml up -d --build
docker compose -f docker-compose.pilot.yml ps         # todos "healthy"
```

## Como o TLS/ACME funciona

- **Produção:** ao subir com um domínio real apontado para o host, o Caddy pede
  automaticamente um certificado ao Let's Encrypt (ACME HTTP-01/TLS-ALPN), renova
  sozinho e redireciona `:80 → :443`. Os certificados ficam no volume `caddy_data`
  (persistente — evita re-emissão e o rate limit do LE em restarts).
- **Teste sem gastar rate limit:** descomente `acme_ca ...staging...` no bloco global
  do `Caddyfile` para usar o staging do Let's Encrypt.

### Dev local (`tls internal`)

O `Caddyfile` já tem um bloco `https://localhost` com `tls internal` — o Caddy emite
um certificado da própria CA interna. Para o Claude Code/curl confiarem sem avisos:

- **Opção A — instalar a CA do Caddy** no truststore do sistema. A raiz fica em
  `caddy_data` (`/data/caddy/pki/authorities/local/root.crt`); exporte-a e importe
  no seu SO/navegador.
- **Opção B — mkcert:** gere um cert local confiável com `mkcert localhost` e monte-o
  no Caddy trocando `tls internal` por `tls /caminho/cert.pem /caminho/key.pem`.

Para dev, use `https://localhost/...` nas variáveis do `.env` (ex.: `AS_ISSUER=https://localhost/auth`).

## Como o Claude Code conecta

Uma vez no ar em `https://mcp.suaempresa.com`:

**OAuth nativo (recomendado):**

```bash
claude mcp add --transport http security https://mcp.suaempresa.com/security/mcp
# 1ª chamada → 401 → o cliente lê o PRM → descobre o AS → faz o fluxo OAuth
# (client_credentials no piloto; authorization_code + PKCE quando ligado) e guarda o token.
```

**Verificação:**

```bash
claude mcp list          # security → connected
claude mcp get security
```

Também dá para pedir um token manualmente (bootstrap `client_credentials`) e passar
via header:

```bash
curl -s -X POST https://mcp.suaempresa.com/auth/oauth/token \
  -d grant_type=client_credentials \
  -d client_id=security-ci -d client_secret=UM_SECRET_FORTE \
  -d resource=https://mcp.suaempresa.com/security/mcp \
  -d scope='security:read security:scan security:model'

claude mcp add --transport http security https://mcp.suaempresa.com/security/mcp \
  --header "Authorization: Bearer <ACCESS_TOKEN>"
```

## Postgres/Redis do gateway

A rede `mcp-private` é `internal: true` (sem egress). Se o Postgres/Redis do
`mcp-gateway` for **externo** ao compose, escolha um:

1. **Adicionar Postgres/Redis a este compose** na rede `mcp-private` (recomendado
   para o piloto — isolado e reprodutível). Aponte `PG_HOST=postgres` etc. no `.env`.
2. **Remover `internal: true`** da rede `mcp-private` no `docker-compose.pilot.yml`
   (o gateway passa a ter egress; os MCPs continuam sem porta publicada, mas perdem
   o isolamento de saída — menos seguro).

O piloto foca em Security + auth-mcp; o gateway só precisa de DB se você exercitar
suas rotas com persistência.

## Notas de segurança

- **Nenhum segredo no git:** tudo por env/`.env` (fora do versionamento) ou secrets
  manager. O `.env.example` só tem placeholders.
- **Só o Caddy é público.** Os MCPs não têm `ports:` — não são alcançáveis do host
  nem da internet, apenas pela borda.
- **Health é público; o resto exige token.** `/security/v1/health` e os `.well-known`
  passam sem auth (necessário para o discovery); `/security/mcp` exige Bearer válido
  com `aud`, `iss`, `exp` e escopo por ferramenta.
- Rode `docker compose ... config` no CI para pegar erro de YAML antes do deploy.
