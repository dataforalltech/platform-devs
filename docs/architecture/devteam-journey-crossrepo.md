# DevTeam Journey — contratos cross-repo (desbloqueio das Fatias B/C/D)

**Status:** proposto · **Data:** 2026-07-21 · **Companheiro de:** `ADR-017-DEVTEAM-JOURNEY.md`

O trabalho da jornada dentro de `platform-devs` está feito até onde é construível+verificável
aqui (ver ADR-017: Fatia A completa + `deploy.sync_repo`). O restante depende de contratos que
vivem em **outros repositórios/serviços**. Este doc especifica exatamente o que cada um precisa
entregar para a jornada seguir — `platform-devs` só **integra**.

## 1. `platform-connectors` — resolução de clone (D17.7) · **A CONSTRUIR**

`deploy.setup_project_workspace(project_id)` e `deploy.sync_repo` precisam, por
`repository_ref`, do bundle de clone. Hoje o connectors **não** expõe isso.

**Contrato pedido (S2S, tenant-scoped):**

```
resolve_repo_clone(repository_ref, tenant_id) ->
  { clone_url: str,          # ex: https://github.com/<owner>/<repo>.git
    default_branch: str,     # ex: main
    auth: { type: "token", token: str } }   # segredo descriptografado p/ uso runtime
```

- A URL pode ser derivada do `RepositoryBinding.external_link` (já canônico em `platform-devs`,
  ADR-017 D17.6), mas a **decisão travada** é que o connectors resolve **URL+auth**; o
  `external_link` fica como referência denormalizada.
- `auth.token` deve sair de `get_credential_runtime` (ver §2), nunca persistido em `platform-devs`.

## 2. `platform-connectors` — credenciais (Fatia B / D17.2) · **JÁ EXISTE, falta integrar**

Regra dura: **credenciais SEMPRE via platform-connectors**; `platform-devs` só integra. Hoje o
domain `config` viola isso (store Fernet próprio em `config_entries`). Tools do connectors já
disponíveis (via gateway hoje, S2S no alvo):

- `create_credential(body, tenant_id)`
- `get_credential(credential_id, tenant_id)`
- `list_credential_services(credential_id, tenant_id)`
- **`get_credential_runtime(credential_id, tenant_id)`** → segredo **descriptografado** (o ponto de uso)

**O que falta (lado connectors):** uma resolução **por serviço/tenant** (hoje `get_credential`
exige o `credential_id` numérico). A jornada precisa: "o token GitHub / chave OpenAI / Anthropic
DESTE tenant" sem o agente saber o id. Opções: (a) endpoint `resolve_credential(service, tenant_id)`;
(b) `platform-devs` guarda só o **mapeamento** `service -> credential_id` (não o segredo) e chama
`get_credential_runtime`.

**O que `platform-devs` faz (Fatia B, quando o acima existir):** remover o `ConfigStore` Fernet de
credenciais; `config_get_credential`/`set_credential` viram adaptador S2S fino ao connectors; o
`deploy.clone_repo`/`sync_repo` param de ler `DEPLOY_GITHUB_TOKEN` e passam a resolver o token via
`resolve_repo_clone`/connectors. **Verificação exige o connectors rodando** (não roda local hoje).

## 3. Ops — G9: deploy do `project-product` no gateway · **A FAZER**

`mcp__dataforall__project-product-mcp_*` NÃO está no catálogo ao vivo. Necessário: build+push do
sidecar + `platform-project-product-api`, registrar no `GATEWAY_MAPPING`, **restart do
platform-mcp** (registry lido só no boot), e seed de ≥1 projeto real com bindings github
(`external_link`). Sem isso, `setup_project_workspace` não tem fonte de bindings ao vivo.

## 4. `platform-devs-agent` — bridge do journal (Fatia D / D17.10) · **OUTRO REPO**

O executor (`app/devs_agent`, repo `platform-devs-agent`) deve **emitir** o journal da sessão nos
hooks task_started/finished: `session_add_task`/`start_task`/`complete_task` + `save_checkpoint` na
conclusão + uma `session` decision por gate HILT, usando o `session_uid` do `session_bootstrap`
(ADR-017 A3) como chave. Hoje o journal é convenção manual (CLAUDE.md) e há duas camadas
não-ligadas (`dev_plans` PG × domain `session`).

## Sequência de desbloqueio
1. **Ops:** G9 (deploy project-product) — barato, destrava a fonte de bindings.
2. **connectors:** §1 (resolve_repo_clone) + §2 (resolve por serviço) — destrava clone+creds.
3. **platform-devs:** Fatia B (creds via connectors) + `setup_project_workspace` (orquestra bindings→clone).
4. **platform-devs-agent:** §4 (bridge do journal).
