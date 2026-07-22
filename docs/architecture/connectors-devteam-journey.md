# platform-connectors — entregas para a jornada DevTeam

**Status:** spec acionável (para execução numa sessão do repo `platform-connectors`) · **Data:** 2026-07-22
**Origem:** `ADR-017-DEVTEAM-JOURNEY.md` + `docs/architecture/devteam-journey-crossrepo.md` (repo `platform-devs`)
**Regra dura:** credenciais e resolução de repositório vivem no **platform-connectors**; o `platform-devs`
apenas **integra** (nunca store próprio de segredo). Este doc lista o que o connectors precisa entregar
para desbloquear as Fatias B e C da jornada.

## Contexto (o que o platform-devs já tem e vai chamar)

Na develop do `platform-devs` já existe:
- `RepositoryBinding.external_link` (owner/repo/url github) — referência **canônica/denormalizada** do repo.
- `deploy.sync_repo` — clone-or-pull idempotente (só a parte git); vai chamar o resolvedor de clone abaixo.
- `session_bootstrap` — sessão project-scoped (o loop nasce daqui).
- Seed pronto (`project-product-mcp-server/scripts/seed_demo_project.py`) — cria produto/projeto + bindings.

O que falta é do **connectors** (+ um passo de ops: deployar o project-product no gateway, fora daqui).

## Modelo de credencial atual do connectors (observado ao vivo, para aterrar)

Tools existentes (namespace `connectors-mcp_*`, tenant-scoped por `tenant_id`):

| Tool | Assinatura | Papel |
|---|---|---|
| `list_credential_platforms(tenant_id)` | — | plataformas unificadas + serviços disponíveis |
| `list_credentials(tenant_id, family?, connector_type_id?, access_level?, search?, ...)` | — | lista credenciais (metadados, sem valor) |
| `list_credential_services(credential_id, tenant_id)` | id numérico | serviços habilitados numa credencial de plataforma |
| `get_credential(credential_id, tenant_id)` | id numérico | metadados de 1 credencial |
| `get_credential_runtime(credential_id, tenant_id)` | id numérico | **valor descriptografado** (uso interno runtime) |
| `create_credential(body, tenant_id)` | payload | cria credencial |

Chave: **`credential_id` é numérico**; resolução hoje exige o id. A jornada não conhece o id — conhece o
**serviço** (github/openai/anthropic) e o **tenant**.

---

## Entrega 1 — Resolvedor de clone git (NOVO) · desbloqueia Fatia C

`deploy.setup_project_workspace(project_id)`/`deploy.sync_repo` precisam, por `repository_ref` (o ref opaco
guardado no `RepositoryBinding`), do bundle de clone.

**Endpoint/tool pedido (S2S, tenant-scoped):**

```
resolve_repo_clone(repository_ref: str, tenant_id: str) -> {
  clone_url: str,          # ex: https://github.com/<owner>/<repo>.git
  default_branch: str,     # ex: main
  auth: { type: "token", token: str }   # token de git descriptografado, escopo de leitura
}
```

- O `repository_ref` mapeia para um **connector repository** (github) já registrado no connectors; o endpoint
  deriva `clone_url`+`default_branch` do connector e o `token` via `get_credential_runtime` da credencial
  github do tenant.
- **Nunca** devolver o token em logs/metadata de outras tools; só neste contrato de runtime.
- `platform-devs` **não** persiste o token — usa no `git clone`/`fetch` e descarta.
- Erros: `repository_ref` desconhecido → 404; sem credencial github p/ o tenant → 409/422 com código estável.

## Entrega 2 — Resolução de credencial por serviço · desbloqueia Fatia B

A jornada precisa de "o token GitHub / chave OpenAI / Anthropic **deste tenant**" sem saber o `credential_id`.
Duas opções (escolher uma; **(a) recomendada**):

**(a) NOVO endpoint de resolução por serviço:**
```
resolve_credential(service: str, tenant_id: str) -> {
  credential_id: int,
  value: str          # descriptografado, uso runtime
}
# service ∈ {"github", "openai", "anthropic", ...} — enum estável mapeado a family/connector_type
```

**(b) Receita com as tools existentes (se não quiser endpoint novo):**
`list_credential_platforms(tenant_id)` → achar a plataforma do serviço → `list_credentials(tenant_id, family=<svc>)`
→ pegar o `credential_id` da credencial ativa → `get_credential_runtime(credential_id, tenant_id)`.
Documentar o **mapeamento serviço→family/connector_type_id** e a regra de desambiguação (qual credencial
usar quando há várias). O `platform-devs` guardaria só esse mapeamento (não o segredo).

## Entrega 3 — Auth S2S + fix do 401 · pré-requisito de 1 e 2

Ao chamar o connectors ao vivo pelo gateway, `list_credential_platforms(tenant_id="dataforall")` retorna
**`http_401 Invalid token`** (o `check_health` passa). Ou seja: o caminho de credencial exige um token válido
para as ops do tenant, e hoje o token propagado não é aceito.

- Definir/documentar o **contrato S2S** que o `platform-devs` (deploy/config) usa para chamar o connectors:
  token interno + `tenant_id` por-request (fail-closed), sem tenant estático.
- **Corrigir o 401** (provisão de PAT/tenant, casing do tenant, ou audiência do inner token) para que
  `resolve_repo_clone`/`resolve_credential`/`get_credential_runtime` funcionem por tenant. É o mesmo tipo de
  problema registrado em execuções anteriores (inner_token/tenant no PAT-exchange).

---

## O que o `platform-devs` faz DEPOIS (não é trabalho do connectors)

1. **Fatia B:** o domain `config` remove o store Fernet de credenciais; `config_get_credential`/`set_credential`
   e o token de clone do `deploy` viram adaptador S2S ao connectors (Entregas 2/3). Sem persistência local de segredo.
2. **Fatia C (orquestração):** `deploy.setup_project_workspace(project_id)` lista os bindings do projeto
   (project-product) → `resolve_repo_clone` por binding (Entrega 1) → `sync_repo` de todos no `REPOS_ROOT`.
3. Ambos ficam **verificáveis** quando 1/2/3 existirem e o project-product estiver no gateway (ops G9).

## Ordem sugerida
Entrega 3 (auth/401) → Entrega 2 (creds por serviço) → Entrega 1 (clone) — em paralelo com o G9 (ops) do lado
do project-product. Depois o `platform-devs` fecha Fatia B + orquestração da C.
