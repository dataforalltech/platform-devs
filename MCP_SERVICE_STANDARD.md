# MCP Service Standard — Serviços MCP seguros em cloud, acessados via Claude Code (Desktop/CLI)

> ⚠️ **SUPERSEDED (2026-07-10).** Este padrão (FastMCP Streamable-HTTP + OAuth-PRM) foi
> substituído pelo **Model-C `mcp_http`** do hub. "Seguir o platform-mcp-gateway" = `mcp_http`
> (carrega o inner token no `_meta`, habilita o PEP per-hop). Ver
> [docs/MCP_COMPLIANCE.md](docs/MCP_COMPLIANCE.md) e `platform-service-template/docs/standards/STD-MCP-001`.

> Padrão de referência para construir, expor e consumir servidores MCP da plataforma.
> Aplica-se a todo novo MCP (DevTeam, system MCPs, data services) e à evolução dos existentes.
> Status: **v1.0 — proposta de padronização**. Autoridade: qualquer MCP em produção DEVE
> atender ao "Definition of Done" da §11.

---

## 1. Objetivo e escopo

Queremos que cada capacidade da plataforma seja um **servidor MCP que roda em cloud** e seja
consumido **localmente** pelo desenvolvedor através do **Claude Code Desktop e/ou CLI**, com:

- **Conexão nativa** do Claude Code (sem shims frágeis como o `mcp-http-wrapper.py`).
- **Segurança de verdade**: identidade real, TLS, autorização por escopo, auditoria.
- **Um único padrão** de esqueleto, transporte, auth e deploy — replicável por copy/paste.

Fora de escopo: MCPs puramente locais (stdio) rodando na máquina do dev. Para esses, use stdio
direto; este padrão trata do caminho **remoto (cloud) → cliente local**.

---

## 2. Estado atual × alvo

| Dimensão | Hoje (no repo) | Alvo (este padrão) |
|---|---|---|
| Transporte remoto | REST custom (`/tools/call`) + shim `mcp-http-wrapper.py` | **Streamable HTTP** (spec MCP 2025‑06‑18), conexão nativa |
| Autenticação | `test-admin-token` hardcoded (`token_validator.py`) | **OAuth 2.1 + PKCE**, gateway como *Resource Server* |
| TLS | Nenhum — HTTP puro em IP público (`28080:8080`) | **TLS obrigatório** via proxy reverso |
| MCP interno | `/tools/call` sem auth na porta 7100 | Rede privada; só o gateway acessa; mTLS opcional |
| Autorização | RBAC estático em `rbac.py` | RBAC + **escopos OAuth por ferramenta** |
| Auditoria | `mcp_audit_log` (bom) | Mantida + correlação por `trace_id` |
| Segredos | defaults commitados (`staging_password_123`) | Secrets manager / env injetado, zero no git |

O objetivo **não** é jogar fora o gateway — é promovê-lo de "proxy com token de teste" para
**edge de segurança padrão-MCP**.

---

## 3. Princípios (inegociáveis)

1. **Secure by default**: sem token válido e sem TLS, o serviço não responde nada além do health.
2. **Least privilege por ferramenta**: cada tool declara o escopo OAuth que exige; deny‑by‑default.
3. **Nunca token passthrough**: o token do usuário é validado no edge e **não** é repassado a
   serviços downstream (anti-pattern explícito da spec MCP → *confused deputy*). Downstream recebe
   uma identidade derivada e assinada pela plataforma.
4. **Rede privada para os MCPs**: nenhum MCP interno é exposto publicamente. Só o gateway tem borda pública.
5. **Tudo auditável**: toda chamada de ferramenta gera log imutável (quem, o quê, quando, resultado, latência).
6. **Human-in-the-loop** para ferramentas destrutivas/irreversíveis (marcadas como `sensitive`).
7. **Um esqueleto só**: todo MCP nasce do template da §8. Divergência é dívida técnica.

---

## 4. Arquitetura de referência

```
┌──────────────────────────┐         Internet / TLS 1.3          ┌───────────────────────────────────────┐
│   Claude Code (local)    │  ────────────────────────────────▶ │            EDGE (cloud)                 │
│  Desktop  ou  CLI        │   HTTPS + OAuth 2.1 (PKCE)          │  Reverse proxy (TLS, Origin check)      │
│                          │ ◀──────────────────────────────── │       │                                 │
│  Cliente MCP nativo      │   Streamable HTTP (JSON-RPC/SSE)    │       ▼                                 │
└──────────────────────────┘                                     │  MCP GATEWAY (Resource Server)          │
                                                                  │  • valida access token (aud, exp, scope)│
        navegador abre p/ login OAuth  ─────────────────────────▶│  • RBAC + escopos por ferramenta        │
                                                                  │  • rate limit (Redis) + audit (PG)      │
                                                                  │  • deriva identidade interna assinada   │
                                                                  └───────────────┬─────────────────────────┘
                                                                                  │  rede PRIVADA (sem borda pública)
                                    ┌─────────────────────────────────────────────┼───────────────────────────┐
                                    ▼                        ▼                      ▼                           ▼
                             security-mcp             qa-engineer-mcp            backend-mcp          … demais MCPs
                          (Streamable HTTP :7100)  (Streamable HTTP)      (Streamable HTTP)     cada um = template §8
                                    │                                                                            
                                    ▼  Authorization Server (OAuth 2.1) — próprio (auth-mcp) ou IdP (Auth0/Entra/Keycloak)
```

**Duas topologias válidas** (escolha uma por serviço; recomendamos a A para a plataforma):

- **A — Gateway como Resource Server (recomendado):** o Claude Code aponta para
  `https://mcp.suaempresa.com/<mcp_name>`. O **gateway** faz OAuth, RBAC, rate limit e audit, e
  encaminha para o MCP interno na rede privada. Um único ponto de política e observabilidade.
- **B — MCP standalone como Resource Server:** o próprio serviço publica OAuth e valida tokens.
  Use só para um MCP isolado que não pertence à plataforma. Duplica esforço de segurança.

---

## 5. Transporte: Streamable HTTP (obrigatório para remoto)

Adote **Streamable HTTP** (transporte remoto atual da spec MCP, sucessor do HTTP+SSE). Um único
endpoint (ex.: `/mcp`) que:

- **POST** recebe mensagens JSON‑RPC do cliente. A resposta é `application/json` (resposta única)
  **ou** `text/event-stream` (SSE) quando a ferramenta faz streaming/progresso.
- **GET** abre um canal SSE para mensagens iniciadas pelo servidor (notificações, progresso).
- **Sessão**: o servidor emite `Mcp-Session-Id` no `initialize`; o cliente reenvia em todo request.
  O ID DEVE ser **não-determinístico, ≥128 bits de entropia, e vinculado à identidade do usuário**.
- **Origin**: o servidor DEVE validar o header `Origin` (defesa contra DNS rebinding). Local: bind em
  `127.0.0.1`. Remoto: allow-list de origens.

Por que isso e não o `/tools/call` custom de hoje: o cliente MCP do Claude Code fala Streamable HTTP
**nativamente**. Ao adotá-lo, o `mcp-http-wrapper.py` deixa de existir e a conexão vira uma linha de config.

**Implementação:** use o SDK oficial (`mcp` Python) — `FastMCP` expõe `streamable_http_app()` que
você monta no FastAPI. Não reimplemente o protocolo à mão (o `HybridMCPServer` atual é REST custom;
migre-o para o app Streamable HTTP do SDK).

---

## 6. Autenticação e autorização (OAuth 2.1)

A spec MCP define autorização sobre **OAuth 2.1**. O MCP (ou o gateway, topologia A) é um
**Resource Server**; o login acontece num **Authorization Server** (o `auth-mcp` promovido a AS, ou
um IdP gerenciado — Keycloak/Auth0/Entra ID). Fluxo:

1. Claude Code chama o MCP **sem token** → recebe `401` com
   `WWW-Authenticate: Bearer resource_metadata="https://mcp.suaempresa.com/.well-known/oauth-protected-resource"`.
2. O servidor publica **Protected Resource Metadata** (RFC 9728) nesse `.well-known`, apontando o
   `authorization_servers`.
3. Claude Code descobre o AS (`/.well-known/oauth-authorization-server`), faz **Authorization Code +
   PKCE** (abre o navegador). Registro do cliente via **Dynamic Client Registration** (RFC 7591) ou
   client pré-cadastrado.
4. O AS emite um **access token** com `aud` = a URL do resource (RFC 8707 *Resource Indicators*) e
   `scope` = escopos concedidos.
5. Claude Code reenvia o token em `Authorization: Bearer …`. O Resource Server **valida
   `aud`, `iss`, `exp`, assinatura e `scope`** a cada request.

**Regras de ouro:**
- Valide o **audience**: rejeite tokens cujo `aud` não seja este resource (evita reuso de token entre serviços).
- **Não repasse o token** para downstream. O gateway, após validar, gera uma **assertion interna
  assinada** (JWT curto, `aud=<mcp interno>`, contém `sub`, `role`, `scopes`, `trace_id`).
- **Escopo por ferramenta**: mapeie `tool → scope mínimo` (ex.: `security:read`, `security:scan`,
  `deploy:write`). A autorização = RBAC (papel) **∩** escopos do token.
- **Atalho pragmático (bootstrap):** enquanto o AS OAuth não sobe, aceite **Bearer estático por
  usuário** — tokens opacos com hash (bcrypt) numa tabela `agent_tokens`, com `expires_at`, `scopes`,
  `revoked`. É o que o `token_validator.py` já promete no comentário; implemente-o de verdade e
  remova os tokens de teste. Claude Code passa via `--header "Authorization: Bearer …"`. Migre para
  OAuth completo em seguida.

---

## 7. Camadas de segurança (checklist do edge)

Ordem no gateway, por request:

1. **TLS terminando no proxy** (Caddy/Traefik/nginx + ACME). HSTS. TLS 1.2+ (ideal 1.3).
2. **Origin / Host allow-list** (anti DNS rebinding).
3. **AuthN**: valida Bearer/JWT (`aud`, `iss`, `exp`, assinatura). Sem token → `401` + `WWW-Authenticate`.
4. **AuthZ**: `is_authorized(user, mcp, tool)` **∩** `scope in token`. Deny-by-default.
5. **Rate limit / quota** por usuário e papel (Redis — já existe). Adicione limite por custo de ferramenta.
6. **Limites de payload**: tamanho máximo de corpo e de argumentos; timeouts por ferramenta.
7. **Sanitização de saída**: nunca devolva segredos/PII crus; o Security `scan_secrets` mascara — reuse.
8. **Human-in-the-loop**: ferramentas `sensitive:true` exigem confirmação explícita (o cliente já pergunta;
   marque no schema e registre a decisão no audit).
9. **Audit imutável** (PG `mcp_audit_log`) com `trace_id` correlacionando request de ponta a ponta.
10. **Egress control** nos MCPs que chamam a internet (allow-list de destinos; defesa a SSRF).

---

## 8. Esqueleto canônico do serviço (template)

Todo MCP remoto nasce assim. Núcleo em Python + SDK oficial, exposto via Streamable HTTP:

```python
# src/server/mcp_server.py  — template padrão
from __future__ import annotations
import os
from mcp.server.fastmcp import FastMCP
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools import registry  # dict: {name: (fn, scope, sensitive)}

mcp = FastMCP(name="<nome>-mcp", instructions=SYSTEM_PROMPT)

for name, (fn, scope, sensitive) in registry.items():
    # cada tool declara: escopo mínimo e se é sensível (human-in-the-loop)
    mcp.add_tool(fn, name=name, annotations={"scope": scope, "sensitive": sensitive})

# Streamable HTTP app (montável no FastAPI/uvicorn); NÃO reimplementar o protocolo
app = mcp.streamable_http_app()

# Health separado, sempre público
@app.get("/v1/health")
async def health():
    return {"status": "ok", "server": "<nome>-mcp"}

if __name__ == "__main__":
    import uvicorn
    # bind em 0.0.0.0 SÓ dentro da rede privada; borda pública é o gateway
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7100")))
```

Estrutura de diretórios padrão (já seguida por security/qa-engineer):

```
<nome>-mcp-server/
├── pyproject.toml            # entrypoint = src.server.mcp_server:main, deps pinadas
├── Dockerfile                # copia SÓ src/ e shared/ (não o repo inteiro)
├── src/
│   ├── prompts/system_prompt.py   # persona/instruções do agente (rico, não placeholder)
│   ├── tools/                      # funções PURAS que recebem input e retornam dict
│   └── server/mcp_server.py        # template acima
└── tests/                          # 1 teste por ferramenta (input→output esperado)
```

**Regras do esqueleto:**
- Ferramentas são **funções puras** (facilita teste e reuso). Efeitos colaterais isolados no store.
- Cada ferramenta: `description` clara, `inputSchema` com tipos e `required`, `scope`, `sensitive`.
- `system_prompt` real (veja Security como referência) — nunca `"""Sistema especialista."""`.
- Sem segredo no código; tudo via env. Defaults nunca são credenciais reais.

---

## 9. Fluxo de conexão do Claude Code (Desktop/CLI)

Uma vez o serviço no ar em `https://mcp.suaempresa.com/<mcp_name>`:

**CLI — com OAuth (recomendado):**
```bash
claude mcp add --transport http security https://mcp.suaempresa.com/security
# Na primeira chamada de ferramenta, o Claude Code recebe 401, descobre o AS
# e abre o navegador para login. O token fica guardado pelo cliente.
```

**CLI — com Bearer estático (bootstrap):**
```bash
claude mcp add --transport http security https://mcp.suaempresa.com/security \
  --header "Authorization: Bearer $SECURITY_TOKEN"
```

**Escopo da config (onde o MCP fica disponível):**
```bash
claude mcp add --transport http --scope user security https://…   # todos os projetos do usuário
claude mcp add --transport http --scope project security https://… # commitado em .mcp.json do repo
```

**Desktop:** Configurações → **Connectors** → *Add custom connector* → cole a URL
`https://mcp.suaempresa.com/security`. O login OAuth abre no navegador; a conexão persiste.

**Verificação:**
```bash
claude mcp list          # deve listar o servidor como "connected"
claude mcp get security  # detalhes/health
```

Repare: **nenhum** `mcp-http-wrapper.py`. A ponte deixa de ser necessária.

---

## 10. Deployment / infra

- **Proxy reverso + TLS** na borda (Caddy é o mais simples: ACME automático). Um único host público;
  roteia `/<mcp_name>/*` para o gateway.
- **Rede privada** (Docker network / VPC) para os MCPs. Remova os `ports:` públicos das portas
  7100/711x — só o proxy/gateway acessa.
- **Segredos** via secrets manager (AWS Secrets Manager / SSM / Vault) injetados como env no boot.
  Remova `staging_password_123` e afins do compose; use `${PG_PASSWORD}` sem default sensível.
- **Health** (`/v1/health`) público e sem auth; **tudo o mais** exige token.
- **Observabilidade**: logs estruturados com `trace_id`; métricas de latência/erro por ferramenta;
  alertas de `403`/`429` anômalos (sinal de credencial vazada ou abuso).
- **CI**: rode o `security.scan_secrets`/`gitleaks` e SCA no pipeline; falhe o build em segredo/CVE crítico.

---

## 11. Definition of Done — um MCP só vai a produção se…

- [ ] Fala **Streamable HTTP** via SDK oficial (sem REST custom, sem wrapper).
- [ ] Publica `/.well-known/oauth-protected-resource` **ou** aceita Bearer validado com `aud/exp/scope`.
- [ ] **Zero** token/segredo hardcoded; tudo por env/secrets manager.
- [ ] Só acessível atrás do gateway/proxy (sem porta pública própria).
- [ ] Cada ferramenta declara `scope` mínimo e flag `sensitive`.
- [ ] RBAC ∩ escopo aplicado; deny-by-default comprovado por teste.
- [ ] Toda chamada auditada com `trace_id`.
- [ ] `system_prompt` real + 1 teste por ferramenta.
- [ ] TLS na borda + validação de `Origin`.
- [ ] Health público responde; qualquer outra rota sem token responde `401`.

---

## 12. Roadmap de migração — status

Piloto **Security + auth-mcp** implementado e verificado (E2E `tests/e2e/test_oauth_security_pilot.py`,
30/30). Ver `security-mcp-server/PILOT.md` e `deploy/`.

1. ✅ **Streamable HTTP:** Security migrado para o app Streamable HTTP do SDK (FastMCP); conexão
   nativa no Claude Code; `mcp-http-wrapper.py` aposentado para este serviço.
2. ✅ **OAuth 2.1:** `auth-mcp` promovido a Authorization Server — JWKS, metadata (RFC 8414), DCR
   (RFC 7591), Authorization Code + PKCE (S256), refresh com rotação, `client_credentials`, resource
   indicators (aud por recurso), escopos por ferramenta. Lib reutilizável em `shared/mcp_auth.py`.
3. ✅ **Persistência & chave:** `shared/oauth_store.py` (Postgres + fallback in-memory); chave de
   assinatura via `AS_PRIVATE_KEY_FILE`/`AS_PRIVATE_KEY_PEM` (secrets).
4. ✅ **TLS + rede privada:** stack em `deploy/` (Caddy + `docker-compose.pilot.yml`) — só o proxy é público.
5. ✅ **Login real na tela de consentimento:** `shared/user_store.py` (bcrypt, Postgres+in-memory)
   valida usuário/senha antes de emitir o code; federação **OIDC upstream** (SSO) opcional e
   config-gated em `auth-mcp-server/oidc_upstream.py` (Entra/Keycloak/Auth0). E2E: 34/34.
6. ✅ **Rollout iniciado:** QA-Engineer migrado para o template (`qa-engineer-mcp-server`, 19 ferramentas,
   escopos `qa-engineer:read|write`, porta 7124) — prova de que o template §8 generaliza.
7. ✅ **Gateway com auth real:** `mcp-gateway/src/auth/token_validator.py` reescrito — `test-admin-token`/
   `test-developer-token` **removidos**; valida static tokens (bcrypt, TTL, revogação) e JWT do
   auth-mcp (JWKS, aud/iss/exp), preservando a interface `UserSession`/RBAC. 18 testes passando.
8. ✅ **Federação OIDC grau de produção:** `auth-mcp-server/oidc_upstream.py` — Authorization Code +
   PKCE(S256) + nonce + state(anti-CSRF) + validação de id_token (JWKS/iss/aud/exp) + mapeamento
   claim→role + tratamento de erro. Fluxo federado completo testado (E2E 44/44). Receitas por
   provedor em `deploy/OIDC_PROVIDERS.md` (Entra/Keycloak/Auth0/Google/Okta).
9. ✅ **Keycloak concretizado:** `deploy/.env.keycloak.example` pronto para preencher + realm
   importável (`deploy/keycloak/realm-mcp.json`: client `mcp-auth-mcp` PKCE, roles, mapper de
   `realm_access.roles` no id_token, usuários demo) + Keycloak de dev
   (`deploy/keycloak/docker-compose.keycloak.yml`) para testar o fluxo federado real. Guia em
   `deploy/keycloak/README.md`.
10. ✅ **Rollout completo do template:** TODOS os 8 DevTeam agora falam Streamable HTTP + auth com
   escopo por ferramenta, reusando `shared/mcp_auth`:
   security(12·`security:*`)·qa-engineer(19·`qa-engineer:*`)·architecture(4·`architecture:*`)·backend(13·`backend:*`)·
   frontend(5·`frontend:*`)·devops(5·`devops:*`)·product-owner(17·`product-owner:*`)·product-manager(5·`product-manager:*`)
   — 80 ferramentas no total. Portas 7118–7125. Cada um verificado (list_tools + call_tool + build_app).
11. ✅ **Stack completo dos 8 DevTeam + Postgres:** `docker-compose.pilot.yml` agora sobe os 8 DevTeam
   (rede privada, sem porta pública), o `auth-mcp`, o gateway e o `postgres` (persistência de
   OAuth clients/codes/refresh + audit do gateway); Caddy roteia `/<devteam>/*` para todos. Só o Caddy
   é público. RESOURCE/PRM derivam de `MCP_PUBLIC_BASE_URL`.
12. ✅ **Gate de CI do "DoD":** `scripts/check_mcp_dod.py` (checker estático do §11) + workflow
   `.github/workflows/mcp-dod.yml` (checker + E2E do piloto + testes do gateway). O gate distingue
   MCP **migrado** (deve passar todo o §11) de **legado** (listado como pendente, não derruba o CI):
   **9/9 migrados passam**; 12 legados aguardam migração.
13. ⏭️ **Pendente — só o que é seu (credenciais/infra):** importar o realm no Keycloak de
   **produção** + injetar o `CLIENT_SECRET` via secrets manager; migrar os 12 MCPs legados restantes
   (dev-twin, audit, config, deploy, docs, infra, pipeline, qa, services, session, ai-governance,
   test) aplicando o mesmo template §8.

---

### Referências normativas
- MCP Specification — Transports (Streamable HTTP) e Authorization (OAuth 2.1).
- MCP Security Best Practices (confused deputy, token passthrough, session hijacking).
- RFC 9728 (Protected Resource Metadata), RFC 8707 (Resource Indicators), RFC 7591 (Dynamic Client Registration), OAuth 2.1 (PKCE).
