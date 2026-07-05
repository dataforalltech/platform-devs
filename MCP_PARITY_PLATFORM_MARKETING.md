# Paridade de Arquitetura MCP — `platform-marketing` × `platform-devs`

> Documento de paridade para decidir como **rever/unificar a arquitetura de MCP** da plataforma.
> Compara, dimensão a dimensão, como cada repositório expõe seus servidores MCP, aponta as
> divergências **nas duas direções** e recomenda o caminho de convergência.
>
> Base factual: análise read-only de `platform-marketing/mcp/**` e do estado atual de
> `platform-devs` (ver `MCP_SERVICE_STANDARD.md`). Caminhos citados são evidência.

---

## 1. TL;DR — veredito

Os dois repos **não estão em paridade** e divergiram em pontos estruturais. Cada lado está à
frente no outro:

- **`platform-devs` está à frente em**: transporte (Streamable HTTP nativo, conexão direta do
  Claude Code) e autenticação de usuário (OAuth 2.1 completo — PKCE/DCR/refresh + federação Keycloak).
- **`platform-marketing` está à frente em**: **governança de plataforma** (usa a lib compartilhada
  `platform-governance` — Twin PEP / DTR standard), **deploy** (Kubernetes + Helm com HPA/ingress/TLS),
  **auditoria por ferramenta** (`@audit_tool` obrigatório, travado no CI), **multi-tenancy** de
  primeira classe e **versão do SDK** (`mcp>=1.23` vs `mcp>=1.10`).

**Sinal central para "rever a arquitetura":** o `platform-devs` construiu um stack de auth
**bespoke** (`auth-mcp` OAuth + `shared/mcp_auth`) enquanto o `platform-marketing` consome um
**padrão de plataforma já existente** (`platform-governance.policy.service_pep.TwinPep`, audience
`mcp:<domínio>`). Ou os dois convergem para um único modelo, ou a plataforma fica com dois padrões
de autorização MCP incompatíveis. **Conclusão (após analisar `platform-governance` §9 e `platform-auth`
§10):** adotar o **`TwinPep`** (governança) como PEP mandatório; **manter** nosso **Streamable HTTP** e
nosso **OAuth front-door** (`auth-mcp`) — porque o `platform-auth` **não tem OAuth nem emite Twin Token**,
e o `platform-devs` é hoje a implementação das peças que faltam. Resta uma **decisão de plataforma** sobre
quem assina o Twin Token (§10.4). **Arquitetura-alvo definitiva em §10.**

---

## 2. Tabela de paridade

| Dimensão | `platform-marketing` (18 MCPs) | `platform-devs` (21 MCPs) | Paridade |
|---|---|---|---|
| SDK MCP | `mcp>=1.23.0`, Python 3.12, FastMCP | `mcp>=1.10`, Python 3.11/3.12, FastMCP + Server low-level | ⚠️ versões diferentes |
| **Transporte remoto** | HTTP **REST custom** via `MCPHttpSidecar`: `/mcp/tools/list`, `/mcp/tools/call` (Starlette) + fallback stdio | **Streamable HTTP nativo** (`/mcp`, FastMCP `streamable_http_app` / helper low-level) | ❌ **divergência crítica** |
| Conexão nativa do Claude Code | ❌ Não (formato REST próprio; precisa de shim ou stdio) | ✅ Sim (`claude mcp add --transport http`) | ❌ |
| **Modelo de auth** | **HMAC pre-shared token** `profile:tenant:hmac_sha256` (`MCPServiceTokenVerifier`) | **OAuth 2.1** (JWT RS256, PKCE, DCR, refresh, PRM) via `auth-mcp` | ❌ **divergência crítica** |
| Login de usuário (Desktop) | ❌ Não há (token de serviço) | ✅ OAuth browser + federação Keycloak | devs à frente |
| **Autorização por ferramenta** | ✅ **Twin PEP / DTR** (`platform-governance`), capabilities `marketing.x.write`, audience `mcp:marketing` | ✅ escopo por ferramenta (`SCOPE_FOR_TOOL`/`TOOL_REGISTRY` + `BearerAuthMiddleware`) — **bespoke** | ⚠️ mesmo objetivo, libs diferentes |
| Descoberta / registro | `gateway_registry.json` estático (namespace, audience, paths, `capability_overrides`) + env `MCP_*_URL` | PRM (`/.well-known/oauth-protected-resource`) + gateway (RBAC/rate-limit/audit) + `.mcp*.json` legado | ❌ modelos diferentes |
| Well-known OAuth | ❌ nenhum | ✅ PRM (RFC 9728) + AS metadata (RFC 8414) | devs à frente |
| **Auditoria** | ✅ `@audit_tool` por ferramenta, **obrigatório** (validado no CI) | audit centralizado no gateway (`mcp_audit_log`); **sem** decorator por-tool nos MCPs | marketing à frente |
| Multi-tenancy | ✅ 1ª classe: `tenant_id` em toda tool + header `X-Tenant-Id` + workspace por tenant | `tenant_id` em claims do token; sem workspace por-tool padronizado | marketing à frente |
| Estrutura do serviço | `src/<name>_mcp/server.py` (tools inline `@mcp.tool @audit_tool`), "Trinity" (API+lib+MCP), `shared/` | `src/server/mcp_server.py` + `src/tools/<name>_tools.py` + `src/prompts/`; `shared/` | ⚠️ ambos válidos, layouts diferentes |
| Lib compartilhada | `mcp/src/shared/` (auth, audit, http_sidecar, governance, tenant_registry) | `shared/` (mcp_auth, oauth_store, user_store) | ⚠️ escopos diferentes |
| **Deploy** | **Kubernetes + Helm** (HPA 2‑8, ingress NGINX, TLS letsencrypt, probes) | **docker-compose** (Caddy TLS + rede privada + Postgres) | ❌ marketing mais production-grade |
| Registry de imagem | ✅ **`d4all.azurecr.io`** (mesmo!), sem `latest` em prod (usa digest SHA) | ✅ **`d4all.azurecr.io/dataforall/3.0/*`** (mesmo!), hoje com `latest` + `v3.*` | ⚠️ mesmo ACR, política de tag divergente |
| Health endpoint | `/health` (sidecar) + `/api/health/{live,ready}` | `/v1/health` | ⚠️ convenção divergente |
| Naming | entry `markai-<name>-mcp`; classe `FastMCP("MarkAI <Domínio> MCP")` | `<name>-mcp-server`; `FastMCP(name="<name>-mcp")` | ⚠️ divergente |

Legenda: ✅ presente/forte · ⚠️ divergência menor · ❌ divergência estrutural.

---

## 3. Divergências críticas (e o que significam)

### 3.1 Transporte — REST custom (marketing) × Streamable HTTP nativo (devs)
O `platform-marketing` expõe HTTP como **REST próprio** (`/mcp/tools/list` + `/mcp/tools/call`,
via `mcp/src/shared/http_sidecar.py`), com `mcp.run()` (stdio) como fallback. Esse é **exatamente o
estágio "REST custom" que o `MCP_SERVICE_STANDARD.md` (§2/§5) identificou como o que precisávamos
abandonar** — um cliente MCP (Claude Code/Desktop) **não conecta nativamente** nesse formato.
O `platform-devs` já migrou para **Streamable HTTP** (endpoint `/mcp` falando JSON‑RPC), que o
Claude Code fala nativamente. → **Aqui, devs é o padrão mais correto.** Convergir marketing para
Streamable HTTP é a mudança de maior impacto para conexão de clientes.

### 3.2 Autenticação — HMAC de serviço (marketing) × OAuth 2.1 de usuário (devs)
Modelos com propósitos diferentes:
- **Marketing:** token HMAC `profile:tenant:hmac` (`shared/mcp_auth.py`) — bom para **serviço↔serviço**
  atrás de um gateway; não há login de usuário nem OAuth.
- **Devs:** OAuth 2.1 completo (`auth-mcp` + `shared/mcp_auth.py`) — bom para **login humano/Desktop**,
  com PRM/DCR/PKCE e federação Keycloak.

Não são mutuamente exclusivos — a arquitetura-alvo provavelmente precisa dos **dois**: OAuth na
**borda** (acesso humano/Desktop) + token de serviço + PEP no **mesh interno** (serviço↔serviço).

### 3.3 Governança — o ponto que motiva "rever a arquitetura"
O marketing **não reinventa autorização**: usa `platform-governance.policy.service_pep.TwinPep`
(`mcp/src/shared/governance.py`), um **PEP (Policy Enforcement Point) de plataforma** com o
"DTR standard", capabilities (`marketing.campaigns.write`) e audience `mcp:marketing`. O devs
construiu autorização **do zero** (`BearerAuthMiddleware` + `SCOPE_FOR_TOOL`). Se `platform-governance`
é o **padrão corporativo**, o devs está divergente e potencialmente **duplicando** o que já existe.
→ **Investigar `platform-governance` é a ação de maior valor estratégico** (ver §5 e §7).

### 3.4 Deploy — Kubernetes/Helm (marketing) × docker-compose (devs)
Marketing roda em **K8s com Helm** (HPA 2‑8, ingress NGINX, TLS letsencrypt, liveness/readiness).
Devs entrega **docker-compose** (Caddy + rede privada + Postgres). Para produção real e escala,
o alvo é K8s — o devs precisará de charts Helm equivalentes. Ponto positivo: **mesmo ACR**
(`d4all.azurecr.io`), então a publicação de imagem já converge (só a **política de tag** diverge:
marketing proíbe `latest` em prod e usa digest; devs hoje publica `latest`).

---

## 4. Onde cada lado está à frente (resumo acionável)

**Adotar DE `platform-marketing` PARA `platform-devs`:**
1. **`platform-governance` (Twin PEP/DTR)** como camada de autorização — em vez do `SCOPE_FOR_TOOL` bespoke.
2. **`@audit_tool` por ferramenta** (auditoria portátil, não só no gateway) — travado no CI.
3. **Kubernetes + Helm** para deploy de produção (charts, HPA, probes) — hoje só temos compose.
4. **Multi-tenancy de 1ª classe** (`tenant_id`/`X-Tenant-Id` + workspace por tenant).
5. **`mcp>=1.23`** (alinhar versão do SDK).
6. **Política de imagem**: proibir `latest` em prod, referenciar por digest SHA.

**Adotar DE `platform-devs` PARA `platform-marketing`:**
1. **Streamable HTTP nativo** (endpoint `/mcp`) — para conexão nativa do Claude Code/Desktop, sem shim.
2. **OAuth 2.1 na borda** (PRM/DCR/PKCE + Keycloak) — para acesso de usuário/Desktop.
3. **Gate de "Definition of Done"** no CI (`scripts/check_mcp_dod.py`) como contrato de padronização.
4. **Federação SSO documentada** (`deploy/keycloak/`, `deploy/OIDC_PROVIDERS.md`).

---

## 5. O sinal estratégico: existe um padrão de plataforma que o devs ignorou?

A evidência mais importante deste estudo: o marketing importa **libs de plataforma compartilhadas**
(`platform-governance`, e provavelmente `platform-auth-lib`/`platform-core-lib` — há dezenas de
`platform-*-lib` em `repositorios/`). O devs **não** consome essas libs — ergueu tudo localmente em
`shared/`.

Isso levanta três perguntas que **precisam** ser respondidas antes de "unificar":
1. `platform-governance` é **mandatório** para todo MCP da plataforma? Se sim, o devs deve migrar
   autorização para o Twin PEP/DTR (e o nosso `SCOPE_FOR_TOOL` vira um adaptador, não a fonte).
2. Existe um **transporte de plataforma** canônico? O marketing usa um `http_sidecar` próprio; o devs,
   Streamable HTTP do SDK. A plataforma precisa escolher **um**.
3. O modelo de **token/identidade** é `profile:tenant:hmac` + `mcp:<domínio>` (marketing) ou JWT
   OAuth com `aud=<resource>` (devs)? Um PEP unificado precisa de um formato único.

> ✅ **Atualização:** a análise dedicada de `platform-governance` foi feita — ver §9 (achado decisivo).
> Resumo: é o **PEP mandatório** da plataforma; nosso transporte sobrevive, nossa autz/emissão pivota.

---

## 6. Convenções a normalizar (baixo esforço, alto atrito se ignorado)

| Item | Marketing | Devs | Alvo sugerido |
|---|---|---|---|
| Health path | `/health` + `/api/health/{live,ready}` | `/v1/health` | padronizar 1 (ex.: `/v1/health` p/ MCP + probes K8s) |
| Naming imagem | `platform-marketing-mcp` / `markai-<x>-mcp` | `<svc>-mcp-server` | convenção única no ACR |
| Namespace ACR | `d4all.azurecr.io` (raiz?) | `d4all.azurecr.io/dataforall/3.0/*` | namespace único versionado |
| Tag em prod | digest SHA (sem `latest`) | `latest` + `v3.*` | **adotar digest/sem-`latest` em prod** |
| Audience | `mcp:<domínio>` | `<resource-url>` | decidir no PEP unificado |

---

## 7. Recomendações de convergência (priorizadas)

**0. (Pré-requisito) Analisar `platform-governance` + `platform-*-lib`.** Descobrir se há um padrão
   corporativo de autorização/transporte/identidade mandatório. Sem isso, qualquer unificação é chute.

**1. Transporte: convergir a plataforma para Streamable HTTP nativo.** Migrar o `http_sidecar` do
   marketing para `streamable_http_app`/helper equivalente. Mantém conexão nativa do Claude Code em
   ambos. (Devs já fez; marketing adota.)

**2. Autorização: um PEP único.** Se `platform-governance`/Twin PEP for o padrão, o devs migra
   `BearerAuthMiddleware`/`SCOPE_FOR_TOOL` para consumir o PEP (nosso escopo por ferramenta vira input
   do PEP, não implementação paralela). Auditoria via `@audit_tool` em ambos.

**3. Identidade em duas camadas:** OAuth 2.1 (devs) na **borda** para humano/Desktop **+** token de
   serviço + PEP no **interior** para serviço↔serviço. Formaliza os dois modelos como complementares.

**4. Deploy: Helm charts para o devs**, reaproveitando o padrão do marketing (HPA, ingress, probes),
   sobre o **mesmo ACR** (já convergente). Alinhar política de tag (digest, sem `latest`).

**5. Governança única:** um só "Definition of Done" (unir o `check_mcp_dod.py` do devs com os smoke
   tests/guards do marketing) valendo para os dois repos no CI.

**6. Convenções (§6):** normalizar health, naming, namespace ACR e SDK (`mcp>=1.23`).

---

## 8. Risco de não alinhar

Dois padrões de MCP na mesma plataforma significam: dois modelos de token incompatíveis, dois
formatos de transporte (um não conecta nativo no Claude Code), governança/auditoria duplicadas,
e deploy heterogêneo — tudo publicando no **mesmo ACR**. Um cliente (ou o gateway central) teria de
falar "dois dialetos". A unificação é mais barata agora (2 repos) do que depois (N repos derivando
de cada padrão).

---

## 9. Achado decisivo — `platform-governance` é o PEP mandatório da plataforma

Análise de `C:\Users\caiog\Documents\repositorios\platform-governance` (lib `platform_governance`
v1.0.2, distribuída como wheel/git privado). É o **DTR — Digital Twin Runtime**: o padrão de
governança/autorização da plataforma.

**O que é:**
- **PEP + PDP embutido, transport-agnóstico** (a lib não importa framework web). Classes-chave:
  `TwinPep.enforce(request, capability=, required_scope=, ...) -> TwinClaims` (`policy/service_pep.py`),
  `GuardedToolRegistry.register(name, handler, capability, required_scope)` + `.dispatch(...)`
  (`policy/pep.py`), `TwinTokenVerifier`+`JwksKeyResolver` (`policy/token.py`), `PDP` com gates
  `IdentityGate`/`ScopePurposeGate`/`MandateGate`/`HiltGate` (`policy/pdp.py`).
- **NÃO emite tokens** — só verifica/decide. Os **Twin Tokens** são emitidos **upstream por
  `platform-auth`**; o JWKS é servido por `platform-admin` (`URL_ADMIN_TWIN_JWKS`). Governance valida
  **offline** via JWKS + policies locais.
- **Token = JWT RS256/EdDSA** com `kid`, claim `token_use=="twin"` (impede confusão com user token),
  `aud=mcp:<serviço>`, `scopes` (tuple), `purpose_id/version` (LGPD/INV-8), `jti` (revogação).
  Capability `<domínio>.<área>.<verbo>` + `required_scope` por ferramenta.
- **Recursos que não temos:** HILT (aprovação humana — `enforce_or_park` → 409 Approval Required),
  purpose grants (LGPD), mandates, checkpoints criptografados (Fernet+KMS), audit central, revogação.

**Mandatoriedade (evidências):** `AGENTS.md` (Parte I universal obrigatória; ordem de startup GOV-004:
platform-auth → platform-admin → platform-governance), `docs/pep-rollout/` (12 MCPs devem adotar
TwinPep), invariante **INV-1** verificado no startup (`assert_all_guarded` — toda tool governada só
alcançável via PEP). Auditoria 2026-06-29: *"nenhum backend MCP tem PEP enforcement ativo"* → rollout
em curso, ninguém concluiu.

### 9.1 Impacto no `platform-devs` — o que MANTER e o que PIVOTAR

| Peça do platform-devs | Frente ao padrão DTR | Ação |
|---|---|---|
| **Streamable HTTP nativo** (transporte) | ✅ Ortogonal (DTR é transport-agnóstico; extrai token de `Bearer`/`X-Twin-Token`/`_meta.twin_token`) | **MANTER** — acerto nosso; marketing deveria adotar também |
| `SCOPE_FOR_TOOL` + escopo por tool | ⚠️ Conceito certo, implementação paralela | **REAPROVEITAR como input** do `GuardedToolRegistry` (nosso map → `capability`/`required_scope`) |
| `BearerAuthMiddleware` (nossa autz) | ❌ Reinventa o `TwinPep` mandatório | **PIVOTAR** → `TwinPep.enforce()` / `GuardedToolRegistry` |
| **`auth-mcp` como EMISSOR** (JWKS/DCR/`/oauth/token`) | ❌ Concorre com o emissor da plataforma (`platform-auth`) | **REPENSAR** — emissor é `platform-auth`; nosso AS não deve emitir Twin Tokens em paralelo |
| `oauth_store`/`user_store` | ❌ Duplicam gestão de identidade da plataforma | **Provavelmente descartar** (plataforma tem IAM próprio) |
| Federação Keycloak / login browser | ❓ Depende do `platform-auth` cobrir login humano p/ Desktop | **INVESTIGAR `platform-auth`** antes de decidir |
| `@audit_tool`, HILT, purpose/LGPD | ✅ Ricos e ausentes em nós | **ADOTAR** via governance |

**Leitura estratégica:** o trabalho de **transporte** (Streamable HTTP) foi correto e **sobrevive**.
O de **autorização/emissão de token** (auth-mcp OAuth AS + BearerAuthMiddleware + oauth/user store)
**reinventou um padrão mandatório** — deve pivotar para: `platform-auth` (emissor) + `platform-governance`
(PEP) + Streamable HTTP (transporte nosso). O `auth-mcp` que construímos, na melhor hipótese, vira uma
**ponte de borda** para login humano/Desktop — e só se o `platform-auth` não cobrir esse caso.

### 9.2 Pergunta em aberto que trava a decisão final

O DTR Twin Token é claramente para **agentes** (`token_use=="twin"`, `sub="agent:..."`). Para um
**humano** conectando o **Claude Code Desktop**, qual token ele recebe e quem o emite?
- Se o `platform-auth` faz o **fluxo OAuth de browser** e emite um token que o `TwinPep` aceita
  (`aud=mcp:<svc>`, escopos) → nosso `auth-mcp`/OAuth é **redundante** (usar `platform-auth`).
- Se o `platform-auth` só emite tokens de **serviço/agente** → nossa borda OAuth (PKCE/Keycloak)
  **complementa** para acesso humano, desde que troque por um token que o PEP valide.

→ **RESPONDIDO** pela análise do `platform-auth` — ver §10 (reconciliação final). Spoiler: o
`platform-auth` **não tem OAuth** e **não emite Twin Token**, então nosso OAuth **não é redundante**.

### 9.3 Arquitetura-alvo unificada (proposta, pós-`platform-auth`)

```
Claude Code (Desktop/CLI)
   │  Streamable HTTP (/mcp)              ← transporte ÚNICO (padrão devs; marketing migra)
   ▼
Borda (Caddy/ingress TLS)
   ▼
MCP (devteam/serviço)
   ├─ transporte: FastMCP streamable_http_app / helper
   └─ autorização: platform_governance.TwinPep.enforce(capability, required_scope)   ← PEP ÚNICO
          │ valida offline
          ▼
      JWKS (platform-admin)   ◀── tokens emitidos por platform-auth (agente + humano?)
      PDP local (scopes/purpose/mandate/HILT)  → audit central (governance)
```
- **Transporte:** Streamable HTTP nativo em toda a plataforma (devs + marketing).
- **Autorização:** `platform_governance` (TwinPep/GuardedToolRegistry) em todos — aposenta autz bespoke.
- **Emissão/identidade:** `platform-auth` (+ `platform-admin` JWKS) — aposenta o `auth-mcp` como emissor.
- **Deploy:** Helm/K8s + ordem GOV-004 (auth → admin → governance → MCPs), mesmo ACR `d4all`.

---

## 10. Reconciliação final — as 3 peças (`platform-auth` + `platform-governance` + transporte)

Análise profunda de `C:\Users\caiog\Documents\repositorios\platform-auth` (IdP mandatório, v1.0.0).
**Este achado CORRIGE o §9.1** (que sugeria descartar nosso `auth-mcp`).

**Fatos decisivos do `platform-auth`:**
- **NÃO é OAuth 2.1 / OIDC.** Sem `/authorize`, `/token`(oauth), `.well-known/openid-configuration`,
  PKCE, DCR. Só: `/api/v1/auth/login` (email+senha → user token), `/internal/service-tokens`
  (service token 15min), `/internal/issue-agent-token` (agente, só dev/sandbox). Evidência:
  `API_CONTRACT.md`, `src/platform_auth/jwt_manager.py`.
- **Não emite o "Twin Token" do DTR.** Tokens têm `type`/`aud=platform-services`/`roles`; **faltam**
  `token_use=="twin"`, `aud=mcp:<svc>`, `purpose_id`, scopes estruturados. → **Ninguém na plataforma
  emite o token que o TwinPep espera** (o modelo DTR está projetado, não ligado; auditoria do
  governance: "nenhum MCP com PEP ativo").
- **JWKS RS256** em `/internal/.well-known/jwks.json` (rotação por `kid`). `platform-auth-lib` faz o
  decode/verify importado pelos serviços.
- **Sem federação externa** (Keycloak/Entra/Google/SAML). IdP não-federado (senha via IAM do governance).
- Os MCPs do próprio platform-auth (`mcp/`, `auth_mcp/`) usam **REST custom + `X-Internal-Token`** e
  **não usam TwinPep** — estágio antigo.

### 10.1 O gap real da plataforma (que o `platform-devs` já preenche)

O modelo DTR (governance) pressupõe um emissor de Twin Token + um front-door — que **não existem**:
1. **OAuth 2.1 front-door** para login humano/Desktop → **inexistente** (o `auth-mcp` do devs tem).
2. **Emissão/troca de Twin Token** (user/agent → token com `token_use=twin`/`aud=mcp:<svc>`/purpose que o
   TwinPep aceite) → **inexistente** (o devs pode assumir isso).
3. **Transporte Streamable HTTP nativo** → **só o devs tem**.
4. **Federação SSO** → **inexistente** (o devs preparou Keycloak).

### 10.2 Veredito reconciliado (keep/pivot definitivo)

| Peça devs | Frente à plataforma real | Ação definitiva |
|---|---|---|
| Streamable HTTP nativo (transporte) | Ninguém mais tem; governance é agnóstico | **MANTER** (vira padrão da plataforma) |
| `BearerAuthMiddleware`/`SCOPE_FOR_TOOL` (autz) | Duplica o `TwinPep` mandatório | **PIVOTAR → TwinPep** |
| `auth-mcp` OAuth (PKCE/DCR/emissão) | platform-auth **não tem OAuth** → gap | **MANTER e reposicionar** como front-door/broker |
| Contrato do JWT (`aud=resource-url`) | Não bate com Twin Token | **ALINHAR** ao contrato Twin Token (token_use/aud/scopes/purpose) |
| Federação Keycloak | platform-auth **não federa** → gap | **MANTER** (upstream do IdP) |
| `user_store` | platform-auth já faz login de usuário | **Reavaliar** (pode delegar ao platform-auth) |
| `oauth_store` (clients/codes/refresh) | necessário p/ o broker OAuth | **Manter** (parte do front-door) |

### 10.3 Arquitetura-alvo definitiva

```
Claude Code (Desktop/CLI)
  │  OAuth 2.1 + PKCE (browser)                     ← FRONT-DOOR (auth-mcp do devs, reposicionado)
  ▼
auth-mcp  (OAuth edge / token broker)
  │  autentica humano via platform-auth (/login) OU Keycloak (federação, upstream)
  │  → emite/troca por TWIN TOKEN (token_use=twin, aud=mcp:<svc>, scopes, purpose)
  │     assinado com chave cujo JWKS o governance confie (coordenar c/ platform-admin)
  ▼
MCP (Streamable HTTP /mcp)                          ← transporte do devs
  └ platform_governance.TwinPep.enforce(capability, required_scope)   ← PEP mandatório
        valida via JWKS + PDP (scope/purpose/mandate/HILT) → audit central
```
- **platform-auth**: IdP de credencial (login user/service/agent) + JWKS. Permanece.
- **platform-governance**: PEP/PDP em todos os MCPs. Adotar.
- **auth-mcp (devs)**: front-door OAuth + broker de Twin Token (a peça que a plataforma não tem).
- **transporte**: Streamable HTTP nativo em todos.

### 10.4 Decisão de plataforma pendente (precisa de ADR/RFC, não é código)

**Quem assina o Twin Token e onde fica seu JWKS?** O governance espera JWKS do `platform-admin`
(`URL_ADMIN_TWIN_JWKS`); o `platform-auth` publica outro JWKS. Duas opções:
- **(A)** nosso broker `auth-mcp` **assina** o Twin Token com uma chave cujo JWKS o governance passa a
  confiar (registrar no conjunto de issuers/JWKS aceitos pelo TwinPep); ou
- **(B)** estender o `platform-auth`/`platform-admin` para **emitir** o Twin Token, e o `auth-mcp` só
  faz o front-door OAuth + troca.

Isso é uma **decisão de arquitetura de plataforma** (donos de auth + governance + admin), pois o modelo
DTR está desenhado mas não implementado. **O `platform-devs` é hoje a implementação mais avançada das
peças que faltam** — recomenda-se levar isso a um ADR conjunto antes de refatorar em produção.

---

### Apêndice — evidências (caminhos)

**platform-marketing:** `mcp/src/shared/http_sidecar.py` (transporte REST), `mcp/src/shared/mcp_auth.py`
(HMAC token + `_PROFILE_SCOPES`), `mcp/src/shared/governance.py` (Twin PEP/DTR), `mcp/gateway_registry.json`
(registro estático), `mcp/pyproject.toml` (`mcp>=1.23`, entry points), `mcp/Dockerfile`, `docker-compose.yml`,
`helm/platform-marketing/values.yaml`, `docs/decisions/adr-0003.md` (padrão Trinity).

**platform-auth (IdP):** `API_CONTRACT.md` (endpoints /api/v1/auth/login, /internal/service-tokens),
`src/platform_auth/jwt_manager.py` (emissão RS256, claims user/service/agent — SEM token_use=twin),
`docs/decisions/adr-0001-auth-agent-bypass.md` (agent token dev/sandbox), `/internal/.well-known/jwks.json`
(JWKS RS256), `mcp/` + `auth_mcp/` (MCPs REST-custom + X-Internal-Token, sem TwinPep). SEM OAuth/OIDC/PKCE/federação.

**platform-governance:** `src/platform_governance/policy/service_pep.py` (TwinPep.enforce/enforce_or_park),
`policy/pep.py` (GuardedToolRegistry), `policy/token.py` (TwinTokenVerifier/JwksKeyResolver, contrato do token),
`policy/pdp.py` (PDP + gates), `policy/models.py` (TwinClaims), `docs/pep-rollout/` (mandatoriedade),
`AGENTS.md` (GOV-004 startup order), `dist_wheel/platform_governance-1.0.2-py3-none-any.whl`. Emissor de token: `platform-auth` (JWKS via `platform-admin`).

**platform-devs:** `MCP_SERVICE_STANDARD.md` (padrão), `shared/mcp_auth.py` (OAuth + BearerAuthMiddleware +
helper Streamable HTTP), `shared/oauth_store.py`, `shared/user_store.py`, `auth-mcp-server/authorization_server.py`
(AS OAuth 2.1), `auth-mcp-server/oidc_upstream.py` (federação), `<devteam>-mcp-server/src/server/mcp_server.py`
(FastMCP Streamable HTTP), `scripts/check_mcp_dod.py` (gate CI), `docker-compose.pilot.yml`, `deploy/` (Caddy/Keycloak).
