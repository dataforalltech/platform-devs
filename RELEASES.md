# RELEASES — o que a frota DEVTEAM entrega hoje

> **Escopo:** capacidade de produto. Arquitetura, segurança, variáveis de ambiente,
> topologia e deploy vivem em [INFRA.md](INFRA.md).
> **Companheiros:** [ROADMAP.md](ROADMAP.md) (o que falta) e [BACKLOG.md](BACKLOG.md) (tarefas).

**Medido em:** `develop` @ `e1ba048`, 2026-08-05.
Os números marcados **[HEAD]** vêm de `scripts/audit_mcp_tools.py` executado neste
commit. O artefato versionado foi regenerado e agora tem um `--check` próprio, então
citá-lo voltou a ser seguro.

> **Nota sobre a cobertura de documentação.** Até 2026-08-05 o auditor lia o próprio
> relatório (`docs/reviews/mcp-tools-quality-baseline.md`, que lista o nome de todas as
> tools) como se fosse documentação. Isso inflava `documented_tools` em **595 tools**.
> Com o laço cortado, a frota tem **374 tools documentadas de 946**, e não 957.

---

## 1. O que existe, em uma frase

A frota declara **18 MCPs** no catálogo. Desses, **3 entregam capacidade a um consumidor
hoje**: `project-product-mcp` (13 tools), `contracts-mcp` (3) e `artifact-provenance-mcp`
(3) — **19 tools governadas** no total. Todo o resto é plano de controle, dependência
externa, código não alcançável ou nome reservado.

O maior volume de código do repositório — as **451 tools despachaveis do `devteam-mcp`**
— **não é capacidade entregue**: o manifesto marca `gateway.enabled: false` e
`registry.enabled: false`, então nada disso é alcançável pelo gateway nem aparece no
runtime registry. Ver §5.

---

## 2. Composição da frota

| Status | Qtd | MCPs |
|---|---|---|
| `active` | 5 | `artifact-provenance-mcp`, `contracts-mcp`, `mcp-gateway`, `mcp-registry`, `project-product-mcp` |
| `experimental` | 4 | `auth-mcp`, `connectors-mcp`, `devteam-mcp`, `scheduler-mcp` |
| `disabled` | 1 | `cache-mcp` |
| `planned` | 8 | `database-ops`, `developer-environment`, `event-ops`, `execution-sandbox`, `feature-flags`, `incident-response`, `observability`, `workflow-orchestrator` |

Fonte: `docs/generated/mcp-catalog.md`. Dos 5 `active`, `mcp-gateway` e `mcp-registry`
são plano de controle e não expõem tools de domínio — sobram **3 provedores de
capacidade ao usuário**.

---

## 3. Os 3 provedores governados

Todos com `gateway.enabled: true`, presentes em `generated/mcp-runtime-registry.json`
e no `docker-compose.yml` gerado.

### 3.1 `project-product-mcp` — 13 tools — a referência de "pronto"

**[HEAD]** 13 declared / 13 listed / 13 dispatchable / 13 catalog / 13 contract /
13 input schema / 13 output schema / 13 tested / 13 documented. **Zero** em todas as 20
listas de lacuna da auditoria.

- Gestão de portfólio: produtos, projetos e vínculo com repositórios.
- 6 das 13 tools são de escrita/exclusão, com aprovação N2 (`product_delete`,
  `project_delete`, `project_repository_detach`) ou `risk=medium` / `blast=tenant`.
- Único da frota com `--cov-fail-under=85` e `--cov-branch`; os demais que declaram
  limiar usam 80.
- Pacote `1.0.0`. Promovido em `06159c5`, 2026-07-21.

É o único MCP da frota que satisfaz o próprio gate de promoção sem exceção. Serve de
referência para o que "pronto" significa aqui.

### 3.2 `contracts-mcp` — 3 tools

**[HEAD]** 3/3/3/3/3/3/3/3/3, zero lacunas. Serve o catálogo canônico de contratos de
tool. Readiness real: `readiness=lambda: load_catalog(REPOSITORY_ROOT)`.

Ponto fraco honesto: **1 arquivo de teste / 6 funções** — a menor margem de teste entre
os `active`, ainda que a superfície seja de apenas 3 tools totalmente contratualizadas.

Pacote `1.0.0`. Promovido em `06159c5`, 2026-07-21.

### 3.3 `artifact-provenance-mcp` — 3 tools

**[HEAD]** 3/3/3/3/3/3/3/3/3, zero lacunas. Controles verificados por leitura: bloqueio
de caminhos sensíveis, teto por arquivo e agregado por lote, `hmac.compare_digest` na
verificação.

> **Ressalva que não pode ser omitida:** `provenance_build_statement` produz um
> documento de proveniência **sem assinatura e sem atestação** — não é verificável por
> terceiro. A descrição da tool é honesta a respeito. É capacidade **incompleta**, não
> stub, e **não deve ser anunciada como "proveniência verificável"**.

Pacote `1.0.0`.

---

## 4. Plano de controle dirigido por manifesto — entregue e sem drift

**2026-07-18, `ef0c001`.** O pipeline manifesto→artefato funciona: `generate_mcp_artifacts.py --check`
no HEAD retorna `OK: generated artifacts match canonical manifests`, exit 0. **[HEAD]**

Gerados a partir de `manifests/mcps/*.yaml`: `docker-compose.yml`, `.mcp.json`,
`generated/mcp-runtime-registry.json`, `docs/generated/mcp-catalog.md` e os schemas.

Validação cruzada implementada em `src/control_plane/manifest_validator.py`: existência
do código local, `cwd` é diretório, Dockerfile existe, colisão de porta de host,
dependência desconhecida, provedor executável dependendo de não-executável, catálogo de
tools existe, cada contrato existe e é referenciado, e nenhum contrato órfão.

**32 contratos versionados** em `contracts/tools/` **[HEAD]**.

Depois dos 3 provedores, este é o ativo de engenharia mais sólido do repositório.

---

## 5. O que **não** conta como entregue

Esta seção é o guardrail do documento. Ignorá-la produz um RELEASES que mente.

### 5.1 As 451 tools do `devteam-mcp`

**[HEAD]** 446 declared / 227 listed / 451 dispatchable / **0 catalog** / 7 contract /
227 input schema / **0 output schema** / **50 tested** / 167 documented.

Nenhuma é alcançável: `gateway.enabled: false`, `registry.enabled: false`, ausente do
`docker-compose.yml` e do runtime registry. Além disso: **48 placeholders**,
**27 tools que retornam sucesso falso**, **401 sem teste**, 409 com nome duplicado
entre domínios.

**A contagem bruta de tools não é métrica de capacidade entregue.** O total da frota é
**946 tools declaradas [HEAD]**, e 19 delas estão governadas.

### 5.2 Quatro sistemas TypeScript que afirmam falsidade

`knowledge-base-mcp`, `quality-gates-system`, `cross-devteam-validators` e
`devteam-observatory` retornam valores fixos:

- `index_documentation` → `{status:'indexed'}` sem escrever nada; a busca posterior
  devolve sempre zero resultados.
- `evaluate_gate` → sempre `{passed:true, score:100}`.
- `validate_handoff` / `check_governance` / `validate_output` → sempre `{valid:true}`.
- `get_devteam_status` → `{status:'healthy', uptime:'100%'}` para qualquer nome.

Em todos os quatro existe um store SQLite completo e implementado que **nunca é
importado**, e **os testes fixam a mentira** (`expect(parsed.passed).toBe(true)`).

Nenhum tem manifesto, nenhum está entre os 18, nenhum está no compose. **Não são
entrega em nenhuma forma.** Destino em [ROADMAP §15](ROADMAP.md), tarefa em
[BACKLOG B08](BACKLOG.md).

### 5.3 Guardian (ADR-018) — construído, testado e inalcançável

Entregue em **2026-07-22**, em um único dia, com 8 merges datados: ADR escrito 05h21,
núcleo versionado de diretrizes 06h39, importador markdown→DB 12h48, schema LCR/handoffs
13h38, corpo tipado e relações 14h08, parser da matriz de rastreabilidade 15h17,
conformance controls + waivers 15h29, `sweep_expired_waivers` 17h27. Inclui correção de
3 bugs achados rodando testes contra MySQL real.

10 tabelas `gov_*` existem. ~26 tools em `src/domains/guardian/catalog.py` (862 linhas),
com testes próprios.

**Por que não entra como capacidade disponível:** `ls platform-catalog/catalog/tools | grep -i guardian`
retorna **0** **[HEAD]**. Não há Provider nem Operation `guardian`, e o domínio vive
dentro do `devteam-mcp`, que tem `gateway: false`.

Decisão de design a preservar (ADR-018 D18.9): guardian é **registro e política**, não
executor — não é chamado no laço de execução.

### 5.4 `platform-catalog` / Discovery — implementado, não publicado

Nasce em `3d4b538`, 2026-07-06. Implementados: envelope ADR-010, derivação determinística,
`CatalogStore` com busca por domínio/recurso/efeito/dono/risco, e API HTTP
(`/v1/operations`, `/v1/providers`, `/v1/assets`, `/v1/stats`, `/v1/production-impact`).

**Mas o conteúdo está estruturalmente presente e semanticamente vazio:** 307 de 307
operations com `contract.inputs: {}` e `contract.outputs: {}` **[HEAD]**. O
`platform-catalog` não tem manifesto próprio, não está entre os 18 e não está no compose.

Anunciar como **"camada de Discovery implementada, não publicada"** — nunca como
"Discovery entregue". Ver [ROADMAP §2](ROADMAP.md).

### 5.5 `cache-mcp` — esqueleto sobre um entrypoint que não inicia

Havia a tentação de classificá-lo como "inventário pronto aguardando uma flag". Não é.
Verificado por leitura no HEAD:

- **`main()` não sobe.** `services/cache-mcp-server/src/server/mcp_server.py:192` chama
  `server.run(sys.stdin.buffer, sys.stdout.buffer)` — 2 argumentos e buffers de bytes
  crus. A assinatura real do SDK que o próprio `pyproject` pina exige
  `initialization_options` posicional e streams vindos de `stdio_server()`. É `TypeError`
  no boot, antes de qualquer tool. O padrão correto está em todos os outros servidores
  (ex.: `audit-mcp-server/src/server/mcp_server.py:529`). **Nenhum dos 4 arquivos de teste
  toca `main()`** — por isso os testes passam sobre um entrypoint quebrado.
- **Não existe superfície HTTP.** Zero ocorrências de FastAPI, uvicorn ou `/mcp/tools` no
  código, embora `manifests/mcps/cache-mcp.yaml:24-26` declare `http: true` com
  `canonical_http` de health/tools_list/tools_call.
- As 7 tools são proxies para uma API `platform-cache` que não existe neste repo nem em
  compose nenhum.

Custo real de reativar: **escrever um servidor Model C do zero**, não ligar uma flag.
Ver [ROADMAP §12](ROADMAP.md).

### 5.6 Os 8 `planned` são apenas o nome

Manifesto de ~15 linhas cada em `manifests/planned/`, com `runtime.mode: none`,
`exposes_tools: false`, CI/gateway/registry desligados e `dependencies: []`. Nenhuma
linha de código, nenhuma operation no catálogo. Grep pelos oito nomes retorna 10
arquivos: os 8 manifestos, o catálogo gerado e uma runbook.

### 5.7 `connectors-mcp` e `scheduler-mcp` — contratos sem código aqui

`runtime.mode: external`, apontando para `dataforalltech/platform-connectors` e
`/platform-scheduler`. Não há diretório local correspondente. Ainda assim o repositório
versiona 5 contratos, **4 deles de operações destrutivas de banco**
(`connectors-drop-db-table`, `connectors-truncate-db-table`,
`connectors-execute-adhoc-sql`, `connectors-alter-db-user-password`).

São **dependência externa**, nunca entrega.

### 5.8 Distinção que precisa ser mantida: scaffold honesto ≠ stub que engana

Nem tudo marcado como "placeholder" pela auditoria é defeito. Os `generate_*` dos
domínios backend/frontend/qa-engineer são **scaffolds honestos**: produzem esqueleto com
`raise NotImplementedError`, a docstring diz "(scaffold — implementar)" e o módulo abre
avisando que usa "defaults/placeholders sensatos… NÃO inventa conteúdo de domínio".
Isso é design correto.

Também verificadas como honestas: `deploy/trigger_workflow` (chama a API do GitHub de
verdade via PyGithub) e `run_linter` / `run_security_scan` / `check_dependencies` do
domínio qa (falham com `error:'tool_not_found'` quando o binário não existe).

O problema desses casos não é a implementação — é que a Operation correspondente no
catálogo tem `description` vazia, então a honestidade nunca chega em quem seleciona a
capacidade. Ver [ROADMAP §2](ROADMAP.md).

---

## 6. Linha do tempo

**397 commits.** Volume por mês, sem merges **[HEAD]**: 2026-05 = 120, 2026-06 = 1,
2026-07 = 225, 2026-08 = 2.

### Tags

| Tag | Data | Observação |
|---|---|---|
| `v2.1.0` | 2026-05-11 | Tag **leve**. `git merge-base --is-ancestor v2.1.0 HEAD` é **falso** — **não é ancestral do HEAD**. Linha paralela abandonada, com 11 commits que nunca entraram na develop. Não tratar como release anterior linear. |
| `v3.0.0` | 2026-07-30 | Tag anotada, commit `bfb674f`. Primeira release cortada desde a v2.1.0. Major por incompatibilidade de nomes de servidor, layout de diretórios e runtime. |

Depois da `v3.0.0` existem apenas 4 commits, em 2026-08-03 e 2026-08-05.

### Maio/2026 — fundação (como "Zillas")

Repositório inicial e migração de 11 MCP servers (09/05); consolidação de 18 servers
(09/05); 8 Zillas com 170 tools e 18 system MCPs como FastAPI (10/05); reescrita dos 10
Zillas de TypeScript para 100% Python (11/05); migração SQLite→PostgreSQL de 14 MCPs;
**`mcp-gateway` entra em 12/05** com rate limiting e auditoria; padronização de
`/v1/health` (13/05).

### Junho/2026 — sem release

1 commit no mês. Buraco de ~7 semanas entre 13/05 e 02/07.

### Julho/2026 — a reorganização

Rename Zillas→DevTeam (05/07, 30.165 arquivos); `platform-catalog` / Capability Registry
(06/07); pentest e remediação de frontends (07-08/07); split de infra para
`platform-infra` (09/07); **Model C nas 7 personas e nos 12 system MCPs** (09-10/07, com
mypy bloqueante e 134 erros de tipo corrigidos); compliance Tier-2 do template (10/07);
ORM canônico dual-db (11-13/07); saída do runtime do agente para `platform-devs-agent`
(14-16/07); qualidade de tools P4a/P4b (17/07); **consolidação `devteam-mcp`** (17-18/07);
**control plane por manifests** (18/07); secure runtime e os 3 provedores governados
(21/07); ADR-017 e ADR-018 (21-22/07); healthcheck bakado e **tag v3.0.0** (30/07).

### Agosto/2026

Pipeline ledger fail-closed (03/08). Credencial por destino e correção do bootstrap de
segredos nos 21 MCP servers (05/08) — ver [INFRA §8 e §9](INFRA.md).

---

## 7. Mudanças de superfície para o consumidor

### 2026-07-18 — fim do acesso local direto

Até então o repositório distribuía os MCPs via `.mcp.json` local, e o desenvolvedor
falava direto com cada servidor. A partir da convergência no plano de controle,
**o `.mcp.json` gerado passou a ser `{"mcpServers": {}}`** — intencional e documentado:
nenhum manifesto ativo declara `transport.stdio: true`.

**Efeito prático:** todo consumo passa obrigatoriamente por `platform-tunnel` + gateway.
**Não existe mais caminho de desenvolvimento local direto.** É a mudança mais sentida por
quem usa a frota no período, e é incompatível com o modo de trabalho da v2.1.0.

O mecanismo está em [INFRA §12](INFRA.md).

### 2026-07-30 — `v3.0.0` é major por quebra de compatibilidade

Nomes de servidor, layout de diretórios e runtime mudaram. A própria mensagem da tag
registra a incompatibilidade.

---

## 8. Mudança de processo a considerar ao ler o histórico

Merges de PR numerados vão de **#11 a #37** e param em **2026-07-17**. A partir de
2026-07-18 as entregas chegam por merge de branch local, sem número de PR. Ao datar uma
entrega: por PR até 17/07, por merge depois disso.

Não há nenhuma issue no GitHub — nem aberta nem fechada. Este documento e o
[BACKLOG.md](BACKLOG.md) são o primeiro registro de rastreamento do projeto.
