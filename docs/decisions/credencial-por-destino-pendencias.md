# Credencial por destino (STD-SEC-002 / ADR-0026) — o que ficou de fora, e por quê

**Data:** 2026-08-05
**Contexto:** adoção do passo 1 da "Estratégia de migração" do
[STD-SEC-002](../../../../private-libs/platform-service-template/docs/standards/STD-SEC-002-service-to-service.md)
no `platform-devs`, decorrente do **ADR-0012 do `platform-infra`** (ratificado em
2026-08-01), recepcionado no hub do template como **ADR-0026**, que substitui a
ADR-0006.

Este documento existe porque a maior parte dos desvios encontrados **não é
acionável neste repositório**, e a ausência de registro faria parecer que a
migração está completa quando não está. Um repositório sem desvio aparente é
indistinguível de um repositório cujos desvios ninguém anotou.

## O que foi feito

O **passo 1** — *extinguir o segredo universal* — no único serviço deste repo que
faz chamada de saída para `/api/internal/*` sob as exceções: o sidecar
`project-product-mcp-server`.

- O destino entra no **nome** do segredo: `internal_api_token__<destino>` no
  Vault, `INTERNAL_API_TOKEN__<DESTINO>` no ambiente.
- `INTERNAL_API_TARGETS`, `SERVICE_TARGET_NAME` e `GOVERNANCE_TARGET_NAME`
  declarados, nunca derivados de `APP_NAME`.
- Recusa de boot para: destino declarado sem credencial resolvida (em **qualquer**
  ambiente), dois destinos com o mesmo valor, e destino igual ao próprio sidecar.
- Perfil próprio do sidecar em `project-product-mcp-server/deploy/service-profile-mcp.yaml`.
  O perfil que já existia é o da **API** (`metadata.name: platform-project-product`),
  e quem chama é o sidecar — declarar os destinos no perfil da API a faria afirmar
  que chama a si mesma.
- No manifesto/compose, os papéis de **aceitar** e **apresentar** deixaram de
  compartilhar o mesmo símbolo (`PROJECT_PRODUCT_INTERNAL_API_TOKEN` para os dois).

Em separado, a correção do bootstrap de segredos dos 21 MCP servers — ver a seção
"Bootstrap de segredos" abaixo.

## O que NÃO foi feito, e por quê

### 1. Camada A (o token target-bound propriamente dito) — BLOQUEADA na frota

O modelo canônico é um JWT RS256 `type=service` com `aud` igual ao nome canônico
do destino, TTL ≤ 60 s, `jti` contra blocklist com falha fechada. O chamador **não
assina**: pede o token ao `platform-auth`.

**O contrato HTTP do emissor ainda não foi publicado pelo `platform-auth`.** Sem
ele, o passo 3 da estratégia de migração está bloqueado para a frota inteira, não
só para este repo. Consequências práticas:

- Nada aqui deve declarar `INTERNAL_AUTH_MODE=target-bound-token`.
- Nenhum serviço pode preencher a lacuna assinando o próprio token — isso é
  exatamente o segundo emissor que a ADR-0026 (§Decisão, item 7) proíbe.

**Ação:** aguardar o `platform-auth`. Não há trabalho a fazer neste repo.

### 2. `auth-mcp-server` assina com a chave RS256 da frota — dono é outro repo

`auth-mcp-server/authorization_server.py` resolve `PLATFORM_JWT_PRIVATE_KEY_FILE`
/ `_PEM` e assina, com `kid=platform-auth-1` e `iss=platform-auth`, um JWT com
`aud=platform-services` — uma **audiência genérica de frota**, que o STD-SEC-002
lista nominalmente entre as proibidas, emitido por um **segundo emissor**, que a
ADR-0026 proíbe no item 7 da Decisão.

Seria o achado mais grave deste repo se ele fosse deste repo. Não é:

```
manifests/mcps/auth-mcp.yaml:
  ownership.source_repo: dataforalltech/platform-auth
  ownership.source_path: mcp
  legacy_source_paths: [auth-mcp-server, services/auth-mcp-server]
  status: experimental
```

O código aqui é **espelho legado**; a fonte canônica vive em
`dataforalltech/platform-auth`. Corrigi-lo aqui divergiria o espelho da fonte sem
corrigir nada em produção. Além disso, `PLATFORM_JWT_PRIVATE_KEY_FILE` e
`PLATFORM_JWT_PRIVATE_KEY_PEM` **não estão provisionados** em nenhum
`docker-compose*.yml`, `manifests/` ou `deploy/` deste repositório — o caminho de
assinatura não está no ar aqui.

> Cuidado ao mexer: o `issue_jwt`/`_mint_access` do mesmo arquivo assina com a
> chave **própria** do AS (`AS_PRIVATE_KEY_FILE`, `kid=auth-mcp-key-1`), publicada
> no JWKS do próprio `auth-mcp`, e é o fluxo `client_credentials` que o
> `docker-compose.pilot.yml` entrega a **oito** servidores via `AS_JWKS_URL`.
> Ele **não** é a violação de emissor único, e removê-lo junto mataria os oito.

**Ação:** abrir no `dataforalltech/platform-auth`. Não tocar no espelho.

### 3. `ADMIN_INTERNAL_TOKEN` — token do TENANT usado como credencial de serviço

`shared/twin_session_client.py` documenta o próprio header como
"`X-Internal-Token` (per-tenant, validado em `PLATFORMS`)". O STD-SEC-002 é
explícito (§MUST NOT): *"O `PLATFORMS.internal_token` — o token do TENANT — MUST
NOT autenticar chamada de serviço. Ele é registro de roteamento e não carrega
identidade de chamador nenhuma."* O risco correspondente no registro canônico é o
**R-16**.

Corrigir o lado do **chamador** aqui não resolve enquanto o lado **validador**
(`platform-admin`) continuar aceitando; e o validador não é deste repo. É também o
passo 4 da estratégia de migração, que vem depois do 3 — hoje bloqueado.

**Ação:** coordenar com o dono do `platform-admin`. Depende do passo 3.

### 4. `GATEWAY_CONTEXT_SIGNING_KEY` — segredo universal com outra roupa

Uma chave HMAC simétrica única, injetada **idêntica** em todos os providers
(`docker-compose.yml`, `manifests/mcps/*.yaml`), verificada em
`mcp-gateway/src/security/context.py`. Um valor que autentica em N destinos é
precisamente a topologia que o passo 1 existe para extinguir — só que aqui o
mecanismo é assinatura de contexto, não credencial de rota interna, e o
STD-SEC-002 não a governa nominalmente.

**Ação:** decidir se o contexto do gateway passa a ser assinado por chave por
destino. Não é exigência direta do STD-SEC-002; é o mesmo raciocínio aplicado a
outra superfície.

### 5. `cache-mcp` — servidor desativado

`services/cache-mcp-server` tem credencial de saída genérica e sem Vault, mas
`manifests/mcps/cache-mcp.yaml` traz `status: disabled`, `gateway.enabled: false`,
`registry.enabled: false`, e o serviço não aparece no compose. Investir ali é
trabalho sobre código que não sobe.

**Ação:** nenhuma, enquanto estiver desabilitado.

### 6. Os 21 MCP servers da "família A" — fora do escopo deste cânone

`architecture`, `audit`, `backend`, `devops`, `frontend`, `pipeline`,
`product-manager`, `product-owner`, `qa-engineer`, `security`, `services`,
`session`, `ai-governance`, `deploy`, `config`, `infra`, `qa`, `test`,
`dev-twin`, `docs`, `devteam` **validam** o inner token Model C e não fazem
chamada de saída para `/api/internal/*` de outro serviço. O STD-SEC-002 governa a
credencial de quem **chama**; não há credencial por destino a introduzir neles.

Isto é uma constatação, não uma dispensa: se algum deles passar a chamar
`/api/internal/*`, entra no passo 1 no mesmo momento.

## Bootstrap de segredos — corrigido fora do escopo do target-bound

Os 21 servers tinham, cada um, uma cópia de `load_secret` que chamava:

```python
VaultSecretsClient(vault_addr).get_secret(key)
```

A API real da `platform-crypto-lib` é `VaultSecretsClient(service=...)` mais
`.get(name, field=...)`. **`get_secret` não existe** e o primeiro posicional é
`service`, não o endereço. A chamada levantava sempre, e o `except Exception`
logo abaixo a engolia e degradava para env — em **qualquer** ambiente, cloud
inclusive. O docstring dizia, textualmente, *"o boot NUNCA quebra por causa do
Vault"*: o oposto do que exigem o STD-SEC-002 (§MUST — falha fechada) e a própria
lib (*"Fail-closed: any auth or fetch error raises KeyUnavailableError and the
service must not start"*).

Os testes não pegavam porque o dublê implementava `get_secret` — validavam uma API
que não existe.

Corrigido em todos os 21, com `runtime_env` propagado e falha fechada em cloud.
Cada suíte ganhou um teste de regressão que afirma que o 1º argumento do cliente é
o **espaço do serviço**, nunca a URL do Vault.

> **Efeito operacional:** um serviço em `RUNTIME_ENV=cloud` que hoje sobe porque
> degrada para env passa a **recusar o boot** se o Vault não responder. É a
> intenção. Confira o provisionamento no Vault antes de promover.

## O que este repositório NÃO consegue verificar sozinho

O próprio STD-SEC-002 declara o limite, e ele vale aqui: das três formas de
segredo universal, só duas são detectáveis de dentro de um processo — aceitar e
apresentar o mesmo valor, e usar o mesmo valor para dois destinos. **Um valor
compartilhado entre serviços diferentes é invisível daqui.** Quem o detecta é a
revisão do provisionamento no Vault.

Ausência de erro no boot não é evidência de que o segredo universal foi extinto.
