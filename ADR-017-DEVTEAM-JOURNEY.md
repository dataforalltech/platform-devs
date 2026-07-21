# ADR-017 — DevTeam Journey (Onboarding, Session Bootstrap, Project→Repos & Workspace)

**Status:** Accepted (decisões travadas 2026-07-21) · implementação faseada · **Date:** 2026-07-21 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-013 (Runtime — o loop plan/execute/validate que esta jornada alimenta), ADR-009 (catálogo capability/operation), ADR-005 (HILT/PEP-PDP), ADR-007 (risk tiers) · **Docs:** `docs/architecture/project-product-domain.md`, `docs/architecture/mcp-control-plane.md`

## Context

A jornada real do usuário DevTeam (majoritariamente em **Claude Code / Codex**) é:

1. Baixar o **platform-tunnel**; ao instalar, ganha acesso aos MCPs + ao **DevAgent**.
2. Ao conectar, o MCP do devteam faz o **bootstrap da sessão** (captura agente + ambiente).
3. Verificar/pedir **credenciais** (GitHub, OpenAI, Anthropic, …), **pasta de repos** e **env vars**.
4. Escolher o **projeto** da sessão. Um projeto tem **N repositórios** ligados por uma **estrutura canônica**
   com **external_link** para o GitHub.
5. Com base nos repos, **clonar ou pull** (organizar o ambiente — um checkout de dev normal).
6. Interagir usando os MCPs/tools: **planejar, executar, validar** — sempre **persistindo no banco do devteam**
   pelas tools.

**Gap-analysis (workflow adversarial, 2026-07-21):** das 6 etapas, **0 existem completas ponta-a-ponta**. Todas
as primitivas existem (session, dev-twin, config, deploy, project-product, devs-agent, connectors), mas quase
nada está **composto**. A jornada é um problema de **orquestração/fiação**, não de tools faltando — somado a
**2 violações** da regra dura de credenciais. Detalhe por etapa em `docs/reviews/` (efêmero) e no corpo desta ADR.

**Topologia (decidida):** o **devteam-mcp roda remoto na nossa Cloud** (EC2/HML), agregado pelo gateway. Isso é
determinante: introspecção server-side de ambiente/físico captura o **container**, não a máquina do dev.

## Decision

**D17.1 — A jornada é orquestração sobre primitivas existentes, não tools novas do zero.** Preferimos mudanças
**aditivas** que reusam as tools atuais (`session_*`, `dev-twin_*`, `config_*`, `deploy_*`, `project-product`,
`devs-agent_*`, `connectors-mcp_*`) a novos subsistemas. Os artefatos novos são poucos e finos: `session_bootstrap`,
`sync_repo`, `setup_project_workspace`, o adaptador de credenciais e a bridge de journal.

**D17.2 — Credenciais SEMPRE via platform-connectors; platform-devs só integra (nunca store próprio).**
Hoje há **2 violações**: o domain `config` guarda `credentials.*` num store Fernet próprio
(`config/db/store.py`) e o `deploy` lê `DEPLOY_GITHUB_TOKEN` do próprio `DeploySettings`. Decisão: reapontar
ambos para `connectors-mcp` (`create_credential`/`get_credential`/`get_credential_runtime`/`test_credential_by_id`)
via adaptador S2S fino, **sem persistência local de segredo**. As duas cópias do config (standalone
`config-mcp-server` + domain `config` consolidado) devem ser reconciliadas.

**D17.3 — A sessão é project-scoped.** `SessionRow`/`start_session` ganham `project_id` (obrigatório na jornada),
um **conjunto de repos** (derivado do projeto), o **agent_client** (D17.4) e o **environment** (D17.5). O `repo`
único vira **opcional**. A sessão é criada no **bootstrap**, antes de escolher/clonar repos.

**D17.4 — "Capturar o agente" = o cliente-agente de código (Claude Code vs Codex), não só o twin humano.** O twin
humano já é capturado por `dev-twin_authenticate`. Falta capturar **qual cliente** o dev usa (Claude Code/Codex +
versão), hoje registrado em lugar nenhum. Vai num campo `agent_client` na sessão, vindo do payload do cliente.

**D17.5 — Ambiente/físico vem de payload do cliente, nunca de introspecção server-side.** Como o devteam-mcp roda
remoto (Cloud), `session_bootstrap` **recebe** o snapshot de ambiente (OS, cwd/REPOS_ROOT proposto, versões,
agent_client) como argumento produzido no lado do cliente/tunnel. As tools `config_get_physical_info`/
`collect_environment_context` (server-side) deixam de ser fonte de verdade da máquina do dev.

**D17.6 — `RepositoryBinding` carrega `external_link` first-class.** Além dos refs opacos
(`connector_ref`/`repository_ref`), o binding ganha um `external_link` canônico de GitHub (owner/repo ou URL).
É referência **canônica/denormalizada** — não substitui o connectors como autoridade.

**D17.7 — A resolução de clone (URL + auth) é do platform-connectors; platform-devs consome.** O connectors
**não** expõe isso hoje — **será implementado lá** (outro repo): dado um `repository_ref`, devolve
`{clone_url, default_branch, auth}`. O platform-devs chama via adaptador S2S. O `external_link` do binding (D17.6)
é a denormalização canônica da mesma referência (para exibição/rastreio), **não** a fonte de auth.

**D17.8 — `session_bootstrap`: uma única tool de onboarding.** Fluxo: `authenticate` (twin) → recebe o snapshot de
ambiente + `agent_client` do cliente (D17.4/D17.5) → cria/resume a **sessão project-scoped** → devolve **status de
credenciais** (o que já está no connectors vs o que falta pedir) + **status de workspace** (repos do projeto:
clonados? sujos?). Idempotente e resumível.

**D17.9 — Workspace: `sync_repo` + `setup_project_workspace`.** `sync_repo(repo, branch)` é **idempotente**
(clona se ausente; senão fetch+checkout+ff-pull, sinalizando dirty/conflito) — corrige o `clone_repo` atual que
**falha se o diretório existe**. `setup_project_workspace(project_id)` lista os bindings do projeto (project-product)
→ resolve clone via connectors (D17.7) → faz `sync_repo` de todos no `REPOS_ROOT` → devolve um manifesto por-repo.

**D17.10 — O loop emite o journal da sessão (persistência é byproduct, não convenção manual).** Hoje o journal do
banco é escrito à mão (convenção do CLAUDE.md) e há **duas camadas não-ligadas**: `dev_plans` (PG do agente) e o
domain `session` do devteam. Decisão: o **domain `session` é o journal canônico**; o executor do runtime emite
`session_add_task`/`start_task`/`complete_task` por item + `save_checkpoint` na conclusão + uma **decisão** por gate
HILT/alto-risco, usando o `session_uid` bootstrapado como chave. O `dev_plans` referencia esse `session_id`.

**D17.11 — Onboarding/tunnel documentado; DevAgent surfaçado.** A conectividade **requer** o gateway hospedado +
tunnel autenticado (sem modo offline). O onboarding precisa: como obter/instalar/autenticar o `dftunnel`, o que ele
injeta de config MCP no cliente (`~/.claude`/Codex), e **surfaçar o `devs-agent_*`** como entrada de orquestração
(hoje ausente de toda doc). A integração client-side do tunnel vive no **repo proprietário** (cross-link).

## Responsabilidades por repositório

| Item | `platform-devs` (aqui) | `platform-connectors` | `platform-tunnel` / ops |
|---|---|---|---|
| Credenciais (D17.2) | adaptador S2S no `config`/`deploy` | **autoridade** (já tem as tools) | — |
| Resolução de clone (D17.7) | consome (adaptador) | **implementar** `{clone_url,default_branch,auth}` por `repository_ref` | — |
| `external_link` no binding (D17.6) | schema/contrato do project-product | — | — |
| Sessão project-scoped + `session_bootstrap` (D17.3/7) | **constrói** | — | fornece payload de ambiente/agent_client |
| Workspace `sync_repo`/`setup_project_workspace` (D17.9) | **constrói** | fornece auth p/ git | — |
| Journal bridge (D17.10) | **constrói** (executor→session) | — | — |
| Deploy do project-product no gateway (G9) | build/registro | — | restart do platform-mcp |
| Onboarding + injeção de config MCP (D17.11) | docs/cross-link | — | **integração client** (proprietário) |

## Plano de implementação (faseado, aditivo)

- **Fatia A — backbone de dados (esta iteração):** `external_link` no `RepositoryBinding` (regenera contrato/catálogo);
  `project_id` + `agent_client` + `environment` + conjunto de repos no `SessionRow`/`start_session` (`repo` opcional);
  tool **`session_bootstrap`**. Tudo em `platform-devs`, sem dependência de connectors/tunnel.
- **Fatia B — credenciais via connectors (D17.2):** adaptador S2S; remover stores próprios; reconciliar config
  standalone × domain.
- **Fatia C — workspace (D17.9):** `sync_repo` (clone-or-pull) + `setup_project_workspace(project_id)` (depende de
  Fatia A + do endpoint de clone do connectors, D17.7).
- **Fatia D — journal (D17.10):** bridge executor→`session_*`.
- **G9 (ops):** deploy do project-product no gateway + seed de projeto real com bindings github.
- **Cross-repo:** endpoint de resolução de clone no `platform-connectors`; onboarding do tunnel (proprietário).

## Consequences

**Positivas:** a jornada passa a ser um fluxo real e resumível; a sessão vira o eixo (projeto+repos+agente+ambiente)
que amarra o loop do ADR-013; credenciais deixam de violar a regra; o journal passa a ser subproduto do loop
(auditoria confiável). Mudanças são aditivas e reusam as tools atuais.

**Negativas / riscos:** dependência cross-repo no `platform-connectors` (resolução de clone) — a Fatia C fica bloqueada
até esse endpoint existir; mudar o schema do `RepositoryBinding` (código recém-mergeado) exige regenerar contrato/
catálogo/artefatos; o `session_bootstrap` depende de o cliente/tunnel produzir o payload de ambiente (contrato novo).

## Open questions (ainda em aberto — não travam a Fatia A)

1. **Env vars e `REPOS_ROOT` ficam no store do `config`** (são configuração, não segredo) **ou a regra se estende a
   qualquer env var com segredo?** (existe `audit_env_files`/`redact_env_secrets`).
2. **O `config-mcp-server` standalone ainda é deployado** ou foi superado pelo domain `config`? (ambos precisam da
   Fatia B para a regra valer em todo lugar).
3. **Árvore de trabalho flat (`REPOS_ROOT/<repo>`) ou aninhada por projeto (`REPOS_ROOT/<project>/<repo>`)?**
4. **Contrato exato do payload de ambiente** que o cliente/tunnel envia ao `session_bootstrap`.

## Mapa dos gaps (G1–G10 do gap-analysis → decisões)

G1 (creds fora do connectors)→D17.2 · G2 (resolução clone)→D17.6/D17.7 · G3 (bootstrap + contexto não persistido)
→D17.3/D17.7/D17.8 · G4 (projeto/workspace não modelados)→D17.3/D17.9 · G5 (clone-or-pull + clone-all)→D17.9 ·
G6 (env no container)→D17.5 · G7 (loop não emite journal)→D17.10 · G8 (tunnel/onboarding)→D17.11 · G9 (project-product
não deployado)→plano/ops · G10 (fonte do agente stale)→ADR-013/repo `platform-devs-agent`.
