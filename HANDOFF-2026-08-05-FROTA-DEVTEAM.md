# Handoff — Credencial por destino, documentação da frota e higiene do catálogo

> **Período:** 2026-08-03 a 2026-08-05. **Estado final:** `develop` e `homol` em `2989f73`.
> **Companheiros:** [RELEASES.md](RELEASES.md), [ROADMAP.md](ROADMAP.md),
> [BACKLOG.md](BACKLOG.md), [INFRA.md](INFRA.md).

## TL;DR

Seis entregas na `develop`, todas mergeadas e promovidas para `homol`. O fio condutor
é o mesmo em quase todas: **componentes que afirmavam ter feito o que não fizeram** —
um bootstrap de segredos que degradava em silêncio, checks de segurança fabricados, um
transporte que devolvia erro dentro de envelope de sucesso, um catálogo que anunciava
capacidade inexistente e um auditor que lia o próprio relatório como evidência.

O repositório ganhou também os quatro documentos de produto que não existiam
(RELEASES / ROADMAP / BACKLOG / INFRA) e **três guardas de drift** que impedem os
números publicados de envelhecerem em silêncio outra vez.

**14 dos 28 itens do BACKLOG estão fechados.** Os 14 abertos estão listados em
§4 — separados entre "precisa da sua decisão" e "trabalho sem bloqueio".

---

## 1. O que foi entregue

| Commit | Entrega |
|---|---|
| `5b03bd6` | Correção dos caminhos relativos após o repo mudar para `dev/product-devteam/` |
| `528d80a` | **Credencial por destino** (STD-SEC-002 passo 1) no sidecar + bootstrap de segredos fail-closed nos 21 MCP servers |
| `285985a` | **RELEASES, ROADMAP, BACKLOG e INFRA** — a primeira fotografia da frota |
| `1340cd5` | **P0**: tools e transporte deixam de afirmar o que não verificaram (B01–B06) |
| `5ae27ce` | **Censo honesto** da frota e os três guardas de drift (B09–B12, B16, B27) |
| `d8feb3f` | **Contrato das 307 Operations** derivado do código (B13) |
| `2873f7e` | **Fan-out dos testes** dos servidores legados para o agregador (B15) |

### 1.1 Credencial por destino — o achado que motivou tudo

O ADR-0012 do `platform-infra` (recepcionado como ADR-0026 no `platform-service-template`)
tornou canônico o **token de serviço target-bound**. Ao aplicá-lo aqui, o achado maior não
foi a falta do padrão — foi que **o bootstrap de segredos nunca funcionou**.

Os 21 MCP servers tinham, cada um, uma cópia de `load_secret` chamando
`VaultSecretsClient(vault_addr).get_secret(key)`. A API real da `platform-crypto-lib` é
`VaultSecretsClient(service=...)` mais `.get(name, field=...)`: **`get_secret` não existe**
e o primeiro posicional é o espaço do serviço, não o endereço. A chamada levantava
`AttributeError` **sempre**, e um `except Exception` a engolia, degradando para variável de
ambiente em **qualquer** ambiente, cloud incluído.

Os testes não pegavam porque o dublê implementava `get_secret` — validavam uma API
inexistente.

> **Efeito operacional a conferir antes de promover para HML:** um serviço em
> `RUNTIME_ENV=cloud` que hoje sobe por degradação passa a **recusar o boot** se o Vault
> não responder. É a intenção, mas confira o provisionamento antes.
>
> **Duas variáveis novas precisam ser provisionadas, com valores DISTINTOS entre si:**
> `PROJECT_PRODUCT_MCP_TOKEN_TO_API` e `PROJECT_PRODUCT_MCP_TOKEN_TO_GOVERNANCE`. Sem
> elas o compose falha no `:?required`.

Detalhe e pendências em [`docs/decisions/credencial-por-destino-pendencias.md`](docs/decisions/credencial-por-destino-pendencias.md).

### 1.2 P0 — parar de mentir

- **`SecurityChecker`**: `no_critical_vulnerabilities` (required) retornava `passed: True`
  com details "not implemented in this phase". Isso criava piso de 2/3 no score que
  alimenta `auto_approve_if_score` — **uma promoção podia ser auto-aprovada por varreduras
  que nunca rodaram.** Agora esses itens são `executed: False`, saem do denominador, e o
  `run_audit` recusa auto-aprovação quando há obrigatório não executado.
- **Scanner de credenciais** — o único check de segurança que roda de verdade — **nunca
  abria `.env`**: testava `suffix`, e `Path('.env').suffix` é `''`.
- **`validate_agent_decision`**: `approved` deixou de ser default. Metade das regras só
  roda quando a mudança está escopada; sem `affected_files` nem `affected_layers` o
  resultado passa a ser `inconclusive`, não aprovação.
- **Transporte HTTP**: erro de execução vai com HTTP 500 e `isError: true`;
  `/mcp/tools/call` recusa com 404 o que não está em `_TOOL_SCHEMAS`; `/ready` ganhou
  handler próprio que verifica a fonte admin.

### 1.3 O laço circular do auditor

Ao dar um `--check` ao auditor, **duas execuções consecutivas do mesmo código sobre a
mesma árvore deram números diferentes**. Causa: `audit_repository` trata como documentação
qualquer `.md` sob `docs/` — **inclusive o próprio relatório que ele escreve**, que lista o
nome de todas as tools. Cada execução fazia a seguinte declarar "documentada" toda tool que
ela mesma tinha acabado de listar.

`documented_tools` estava inflado em **595 tools**. A frota tem **374 documentadas de 946**,
não 957.

### 1.4 Contrato das Operations

As 307 Operations tinham `contract.inputs: {}`, `outputs: {}` e 288 sem descrição — todas
`lifecycle: stable`. Agora `description` e `inputs` vêm do código (266/307), e `outputs`
dos contratos canônicos (19/307).

**O preenchimento revelou 37 Operations `stable` que nenhuma tool implementa.** Foram para
`lifecycle: retired`. Nem todas são abandono: `security.calculate_cvss` foi deliberadamente
dobrada em `save_cvss_assessment` — o catálogo é que não acompanhou.

### 1.5 Fan-out dos testes

O fan-out de 2026-07-17 copiou o código mas **não os testes**: os legados tinham 150
arquivos / 2.123 funções, o agregador tinha 7 / 99. Portei 40 arquivos / 438 funções.

**`devteam-mcp`: 50 → 157 tools testadas.** Suíte do agregador: 99 → **576 passed**.

---

## 2. Correções que fiz nas minhas próprias afirmações

Registradas aqui porque quem ler os documentos antigos vai encontrar a versão errada.

1. **"936 tools declaradas"** → **946**. O primeiro número veio do artefato versionado, que
   estava 15 dias defasado. Corrigido, e agora há um `--check` que impede repetir.
2. **"51 tools com sucesso falso"** → **48**. Mesma causa.
3. **"As duas cópias são byte-a-byte idênticas"** (ROADMAP §14) → vale para 17 dos 21
   domínios. **`deploy` (7 arquivos), `session` (5), `pipeline` (4) e `infra` (2)
   divergiram.** No `pipeline` a divergência é comportamental, então o domínio inteiro
   ficou fora do fan-out de testes.

---

## 3. Como verificar que está tudo de pé

```bash
python scripts/generate_mcp_artifacts.py --check && python scripts/audit_mcp_tools.py --check && python scripts/reindex_platform_catalog.py --check
```

Os três devem sair com `exit 0`. Suítes: `pytest tests/control_plane` (17 passed),
`pytest platform-catalog/tests` (27 passed), `cd devteam-mcp-server && pytest tests/`
(576 passed, 45 skipped).

**Falhas pré-existentes que NÃO são regressão** — verificadas por `git stash` contra a
develop limpa: `ai-governance-mcp-server/tests/test_pr_validate.py` (3) e
`test_tool_count`/`test_health`/`test_tools_list_has_policy_fields` em `devops`,
`frontend`, `product-manager` e `product-owner` (3 cada).

---

## 4. O que está aberto

### 4.1 Precisa da sua decisão

| Item | Decisão |
|---|---|
| **B07/B08** · 4 stubs TypeScript | Apagar, reescrever contra o store que já existe, ou declarar `planned`. Hoje retornam `{passed:true, score:100}` fixo e os testes travam a mentira. [ROADMAP §15](ROADMAP.md) |
| **B14** · 317 bindings do catálogo | Depende de decidir o modelo de provider: por-domínio dentro do `devteam-mcp`, ou provider único. [ROADMAP §3](ROADMAP.md) |
| **B28** · `frontend-pixelfera-mcp-server` | Órfão explícito desde que removi a reivindicação falsa do manifesto. Remover ou consolidar. |
| **As 37 Operations `retired`** | Apagar do catálogo, ou reimplementar a capacidade que anunciavam. |
| **Rotação de segredos** | `e04bbe8` registra "Segredos pendentes de ROTAÇÃO pelo dono" e **não há evidência posterior**. Como a remoção foi commit normal, os valores seguem alcançáveis no pai. [INFRA §18](INFRA.md) |
| **Promover `main`** | 13 commits atrás de `develop`/`homol`. É decisão de release. |

### 4.2 Trabalho sem bloqueio

- **B15 (resto)** — 294 tools ainda sem teste. Os 67 arquivos que faltam exigem **MySQL
  real**, e este repositório não tem executor de CI que o suba ([INFRA §15](INFRA.md)).
- **B17** — o gate de Definition of Done **sempre passa**: classifica todos os 21 servers
  como "pendentes de migração, não avaliados". Um gate que sempre passa é pior que gate
  ausente.
- **B19** — 4 bancos SQLite versionados. Não abrir `knowledge-base.db` (45 KB, o único com
  conteúdo) antes de decidir B07.
- **B20** — ~80 documentos de plano/status na raiz sem índice de vigência. Sintoma vivo: o
  validador de token do gateway **em produção** aponta para um documento superseded.
- **B18, B21–B26** — higiene, detalhada no BACKLOG.

### 4.3 Bloqueado fora deste repositório

- **Camada A do target-bound** — o contrato HTTP do emissor não foi publicado pelo
  `platform-auth`. Nada aqui deve declarar `INTERNAL_AUTH_MODE=target-bound-token`, e
  **nenhum serviço pode preencher a lacuna assinando o próprio token**.
- **`auth-mcp-server`** assina com a chave RS256 da frota emitindo `aud=platform-services`
  — audiência genérica, proibida. Mas é **espelho legado**
  (`source_repo: dataforalltech/platform-auth`) e as variáveis não estão provisionadas em
  nenhum compose daqui. Abrir no repo dono.
- **ADR-017 Fatia C/D**, **ADR-018 D18.10** — dependem de `platform-connectors`,
  `platform-devs-agent` e `platform-service-template`.

---

## 5. Armadilhas do ambiente

- **`GITHUB_TOKEN` inválido no ambiente** sobrepõe a credencial boa do keyring e quebra o
  `gh`. Remova a variável antes de usá-lo. Para comandos `git` puramente locais é
  desnecessário.
- **Não existe CI neste repositório.** GitHub Actions foi aposentado em 2026-07-15 e
  **é proibido criar `.github/workflows`** — a proibição é aplicada por
  `scripts/check_mcp_runtime_quality.py`. Todo manifest declara `coverage_threshold: 80` e
  **nada o executa**.
- **260 skips condicionais em MySQL**, em 89 arquivos. Sem CI que suba o banco, **a suíte
  pode passar verde com quase tudo pulado**.
- **Outra sessão pode estar mexendo em `platform-infra`.** Em 2026-08-04 observei o HEAD
  daquele repo mudar entre dois comandos meus. Se precisar dele, use `fetch` + leitura de
  `origin/develop` em vez de mexer na working tree.
- **Dependências de teste ausentes** por padrão: instalei `networkx`, `psutil` e `PyGithub`
  no Python local; sem elas, 5 suítes nem coletam.

---

## 6. Fora de escopo, e por quê

**`product-fit` não foi tocado.** Uma mensagem no meio da sessão pediu foco nele e a
seguinte corrigiu para `product-devteam`; segui a última. No levantamento inicial havia 4
repos com alterações não commitadas lá: `platform-fit-health` (7 arquivos),
`platform-fit-mdm` (7), `platform-fit-training` (7) e `platform-fit-schedule` (1).

**Os outros ~84 repositórios sob `~/dev` também não.** O escopo foi confirmado como
`product-devteam` no início da sessão. `platform-infra` tem 4 PRs abertos, 6 branches não
mergeadas e teve uma worktree ativa.

---

## 7. Estado do repositório

| | |
|---|---|
| Branches locais | `develop` (atual), `main` — nenhuma órfã, nenhuma não-mergeada |
| Remotas | `develop` e `homol` em `2989f73`; `main` em `bfb674f` |
| Worktrees | só a principal; `prune` executado |
| Working tree | limpo |
| Stashes | nenhum |
| PRs / issues | **nenhum** — o BACKLOG é o registro de rastreamento do projeto |
