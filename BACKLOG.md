# BACKLOG — tarefas da frota DEVTEAM

> **Escopo:** capacidade de produto. Tarefas de arquitetura, segurança, variáveis de
> ambiente, CI e deploy vivem em [INFRA.md](INFRA.md).
> **Companheiros:** [RELEASES.md](RELEASES.md) (o que existe) e [ROADMAP.md](ROADMAP.md) (o que falta).

**Medido em:** `develop` @ `f6ba78f`, 2026-08-05. Caminhos relativos à raiz do repositório.

Não há nenhuma issue no GitHub — nem aberta nem fechada. Este arquivo é o registro de
rastreamento do projeto até que exista outro.

**Prioridades:**
- **P0** — corrige algo que hoje **afirma falsidade** ou **aprova indevidamente**.
- **P1** — destrava capacidade.
- **P2** — higiene e consistência.

---

## P0 — parar de mentir

### B01 · Remover os dois checks fabricados do `SecurityChecker`

> **✅ Concluído** — SecurityChecker: os dois checks de vulnerabilidade passam a `executed=False` e saem do denominador do score; o `run_audit` recusa auto-aprovacao quando ha obrigatorio nao executado. Corrigido nas duas copias.

`devteam-mcp-server/src/domains/audit/checkers/security_checker.py:42-62`
e a cópia byte-a-byte em `audit-mcp-server/src/checkers/security_checker.py:49,60`.

`no_critical_vulnerabilities` (required=True) e `no_high_vulnerabilities` retornam
`passed: True` com details "Vulnerability scanning not implemented in this phase".
Trocar para `passed: False` com details "não executado", **ou** removê-los do cálculo do
score (não contar no denominador).

**Por quê:** criam um piso de 2/3 no score de security mesmo quando o único check real
falha. Esse score entra na média de `audit_tool.py:77`, é comparado a
`auto_approve_if_score` e produz `auto_approved` → `gate_tool.py:26` devolve
`passed=True`. **Uma promoção pode ser auto-aprovada por checagens de vulnerabilidade que
nunca rodaram.**

Corrigir nas **duas** cópias (ver [ROADMAP §14](ROADMAP.md)).

### B02 · Corrigir o filtro de arquivos do `_scan_for_credentials`

> **✅ Concluído** — Varredura de credenciais: `.env` reconhecido por NOME, exclusao por diretorio conhecido em vez de "comeca com ponto", teto elevado para 5000 e truncamento sinalizado (varredura truncada vira INCONCLUSIVA, nao aprovada).

`devteam-mcp-server/src/domains/audit/checkers/security_checker.py:74-104` (linhas 85 e 89).

1. `if file_path.suffix not in [".py",".yaml",".yml",".env",".conf"]` **nunca casa
   `.env`**, porque `Path('.env').suffix == ''` e `Path('.env.local').suffix == '.local'`.
   Checar `name` além de `suffix`.
2. `if any(part.startswith(".") for part in file_path.parts)` exclui `.env` uma **segunda**
   vez. Restringir a exclusão a diretórios conhecidos (`.git`, `.venv`, `node_modules`,
   `__pycache__`).
3. `max_files: int = 100` corta a varredura **sem sinalizar truncamento**. Sinalizar no
   retorno quando o teto for atingido.

**Por quê:** o alvo de maior valor para credencial hardcoded é exatamente o arquivo que o
scanner nunca abre, e um repositório maior passa "limpo" em silêncio. **Este é o único
check de segurança que roda de verdade.**

### B03 · Inverter o default de `validate_agent_decision` para fail-closed

> **✅ Concluído** — `validate_agent_decision`: `approved` deixa de ser o default. Passa a ser calculado no fim como `not blocking and not inconclusive` — sem `affected_files` nem `affected_layers` as regras de camada nao rodam, e o resultado e INCONCLUSIVO.

`devteam-mcp-server/src/domains/ai-governance/tools/decision_tool.py:186` (inicializa
`approved = True`), com inversões em 200, 213, 221, 233, 239, 247, 330 e retorno em 355-356.

Inicializar `approved = False` e exigir enquadramento explícito em regra conhecida para
aprovar.

**Por quê:** uma decisão de agente que não bate com nenhuma regra sai **aprovada**. O
propósito declarado na própria docstring é barrar "fallback silencioso, hardcoded de
credencial, bypass de auth, mock em prod" — um validador com default de aprovação não faz
isso.

### B04 · Marcar erro de tool como erro no transporte HTTP do `devteam-mcp`

> **✅ Concluído** — Falha de execucao passa a devolver HTTP 500 com `isError: true`, em vez de payload de erro dentro do envelope de sucesso.

`devteam-mcp-server/src/server/mcp_server.py:277-281`.

O `except Exception` genérico transforma qualquer exceção em
`{"error":"internal_error","tool":name}` e devolve **dentro do envelope de resultado
normal**, com HTTP 200 e sem `isError`. Devolver status HTTP de erro ou `isError: true`.

**Por quê:** para o gateway e para o agente consumidor isso é indistinguível de execução
bem-sucedida cujo retorno por acaso tem uma chave "error". É a mesma classe de problema
dos stubs que mentem, gerada pelo **transporte**.

### B05 · Fazer o `/v1/health/ready` do `devteam-mcp` verificar alguma coisa

> **✅ Concluído** — `/v1/health/ready` ganhou handler proprio e verifica a fonte admin com `SELECT 1` no pool dedicado de health; 503 quando nao responde. `/live` segue sem depender do banco.

`devteam-mcp-server/src/server/mcp_server.py:215-223`.

As três rotas `/v1/health`, `/v1/health/live` e `/v1/health/ready` estão decoradas sobre
o **mesmo handler**, que devolve `{'status':'ok', ...}` sem tocar banco nem pools. Separar
o handler de `/ready` e nele checar banco e pools por tenant.

Referência correta no repositório: `contracts-mcp-server/contracts_mcp/server.py:162`
passa `readiness=lambda: load_catalog(REPOSITORY_ROOT)`.

**Por quê:** o manifesto declara `health_ready: /v1/health/ready`; o orquestrador considera
o serviço pronto com o MySQL fora, e a primeira chamada de tool falha em
`_ensure_tenant_schema`.

### B06 · Gatear `/mcp/tools/call` por pertencimento a `_TOOL_SCHEMAS`

> **✅ Concluído** — `/mcp/tools/call` recusa com 404 qualquer nome fora de `_TOOL_SCHEMAS`, antes do dispatch. A superficie executavel passa a ser exatamente a publicada.

`devteam-mcp-server/src/server/mcp_server.py:240-276`.

`http_call_tool` checa apenas `_EXCLUDE_TOOLS` (denylist de 6 tools de segredo) e delega
direto ao `_dispatch`. Adicionar `if name not in _TOOL_SCHEMAS: return 404` **antes** do
dispatch. Complementarmente, replicar em todos os domínios a asserção que só o `deploy`
tem: `assert set(_POLICY.keys()) == set(_TOOL_SCHEMAS.keys())`
(`src/domains/deploy/catalog.py:1133`).

**Por quê:** qualquer nome que o dispatch de um domínio saiba rotear **executa**, mesmo
sem constar em `/mcp/tools/list` — e portanto sem capability nem `required_scope`
publicados para o gateway policiar. Isto explica materialmente parte da divergência
**227 listed vs 451 dispatchable [HEAD]**.

### B07 · Decidir e executar o destino dos 4 stubs TypeScript

`knowledge-base-mcp/src/tools/index.ts:68-100`;
`quality-gates-system/src/tools/index.ts:76-99`;
`cross-devteam-validators/src/tools/index.ts:70-105`;
`devteam-observatory/src/tools/index.ts:64-102`.

Os handlers retornam valores fixos (`{status:'indexed'}`, `{passed:true, score:100}`,
`{valid:true}`, `{status:'healthy', uptime:'100%'}`) **enquanto existe um store SQLite
completo e implementado que nunca é importado** (`src/db/store.ts` em cada um).

Três saídas: ligar o store ao dispatch; fazer os handlers falharem honestamente com
`not_implemented`; ou remover os diretórios. Decisão em [ROADMAP §15](ROADMAP.md).

**Por quê:** um agente instruído a indexar um ADR recebe "indexed successfully" e o
conteúdo se perde; a busca posterior devolve zero, indistinguível de base vazia. Uma
ferramenta de observabilidade que sempre diz "healthy" **desarma** a checagem em vez de
sinalizar que não sabe.

### B08 · Corrigir os testes que travam a mentira

`knowledge-base-mcp/tests/tools.test.ts:23`;
`quality-gates-system/tests/tools.test.ts:31-40`;
`devteam-observatory/tests/tools.test.ts:28`.

Reescrever para exercitar o **contrato real** (persistir e ler de volta), não o valor
hardcoded.

**Por quê:** é o mesmo padrão que deixou o bug do Vault passar por meses — o dublê
implementava uma API inexistente (`get_secret`) e o teste validava a API errada
(`docs/decisions/credencial-por-destino-pendencias.md`). Vale uma **política de teste**
explícita: *dublê de dependência externa deve espelhar a assinatura real da lib.*

---

## P1 — destravar capacidade

### B09 · Regenerar o baseline de qualidade das tools

`generated/mcp-tools-audit.json` e `docs/reviews/mcp-tools-quality-baseline.md`.

```bash
python scripts/audit_mcp_tools.py --output docs/reviews/mcp-tools-quality-baseline.md --json-output generated/mcp-tools-audit.json
```

**Defasagem confirmada executando o gerador no HEAD.** O artefato versionado diz
`devteam-mcp` = 414 declared / 195 listed / 419 dispatchable / 15 tested, total 904.
O HEAD produz **446 / 227 / 451 / 50**, total **936 declared / 489 listed / 973
dispatchable / 559 tested**. O baseline ainda lista uma linha `auth-mcp | services/auth-mcp-server`
para um diretório que não existe mais.

**Por quê:** qualquer documento — inclusive estes três — que cite maturidade a partir do
artefato versionado cita número errado.

### B10 · Adicionar o baseline de qualidade ao guarda de drift

`src/control_plane/artifact_generator.py:292-306` (`check_all`).

`check_all` cobre `.mcp.json`, o runtime registry, `docker-compose.yml`, o catálogo
gerado e os schemas — **mas não** `generated/mcp-tools-audit.json` nem
`docs/reviews/mcp-tools-quality-baseline.md`. Incluí-los.

**Por quê:** sem isso os números de maturidade envelhecem em silêncio, que é exatamente o
que aconteceu (B09). Não há CI que os regenere — ver [INFRA §15](INFRA.md).

### B11 · Corrigir a description e os `legacy_source_paths` do manifesto do `devteam-mcp`

`manifests/mcps/devteam-mcp.yaml:4` e `:13-34`.

1. A description diz "the twenty DevTeam persona and system domains". **[HEAD]**
   `src/domains/` tem **21** domínios reais. Corrigir.
2. `grep guardian manifests/mcps/devteam-mcp.yaml` retorna **vazio**, embora `guardian`
   exista desde 2026-07-22. Adicionar.
3. `legacy_source_paths` lista `frontend-pixelfera-mcp-server`, mas **não existe** domínio
   `frontend-pixelfera` em `src/domains` — o fan-out nunca o incluiu.

**Por quê:** o manifesto é a fonte canônica que gera o catálogo e os artefatos de runtime,
e seu único commit é de 2026-07-18. Ele afirma uma consolidação que não aconteceu e
desconhece um domínio inteiro.

### B12 · Regenerar `platform-catalog/catalog/index.json`

`platform-catalog/catalog/index.json:3-8`.

Declara 288 operations / 298 tools / 20 providers; no disco há **307 / 317 / 23**
**[HEAD]**. Foi escrito em 2026-07-06 e é o único commit que o tocou, enquanto
`catalog/tools` e `catalog/operations` receberam entradas em 2026-07-21.

**Por quê:** o arquivo que se apresenta como índice do catálogo está 15 dias e 3
providers atrás do próprio catálogo.

### B13 · Preencher `contract.inputs` / `contract.outputs` / `description` das operations

`platform-catalog/catalog/operations/*.yaml` — **307 arquivos**.

Exemplo canônico do problema: `development__generate_fastapi_router.yaml` tem
`metadata.description: ''`, `contract.inputs: {}`, `contract.outputs: {}`,
`preconditions: []`, `postconditions: []` — e ainda assim `lifecycle: stable`.

**[HEAD]** inputs vazio em 307/307, outputs vazio em 307/307, description vazia em 288/307.

**Por quê:** é a camada que agentes e runbooks consultam para **selecionar** uma
capacidade, e ela só carrega o id. **Maior razão valor/esforço do backlog, sem bloqueio
externo.** Ver [ROADMAP §2](ROADMAP.md).

### B14 · Corrigir os 317 bindings de tools do `platform-catalog`

`platform-catalog/catalog/tools/*.yaml`.

Exemplo: `qa-mcp-run_security_scan.yaml` declara `spec.provider_id: qa-mcp` e nome de tool
**sem prefixo**. O runtime real é o `devteam-mcp` em `POST /mcp/tools/call` com nomes
**prefixados por domínio** (`qa_run_security_scan`). Reapontar `provider_id`, endpoint e
nome. Criar o provider `devteam-mcp` (hoje inexistente entre os 23) e as entradas de
`guardian` (hoje zero).

**Por quê:** **nenhum** dos 317 bindings resolve contra o runtime da frota. É por isso que
a auditoria reporta `catalog_tools = 0` para o `devteam-mcp`.

### B15 · Escrever testes por domínio no `devteam-mcp`

`devteam-mcp-server/tests/` — hoje 6 arquivos `test_*.py` para **21 domínios** **[HEAD]**.
O `conftest.py:1-8` admite: "Testes de integração chegam no fan-out da Fase 2/3, por
domínio".

Criar diretório de testes por domínio. Referência de volume nos servidores legados:
architecture 5 arquivos/59 funções, backend 5/70, qa-engineer 5/71, session 5/100,
pipeline 8/84, ai-governance 15/300, services 16/197.

**Por quê:** 401 de 451 tools sem teste **[HEAD]** contra `--cov-fail-under=80` declarado
no próprio `pyproject.toml`. **É o bloqueio nº 1 da promoção do produto** —
[ROADMAP §1](ROADMAP.md).

---

## P2 — higiene e consistência

### B16 · Consertar o ponto cego do discovery da auditoria

`scripts/audit_mcp_tools.py:132` — filtro por nome mais um caso especial hardcoded faz
com que `cross-devteam-validators` e `quality-gates-system` **nunca sejam enumerados**,
apesar de serem MCP servers com entrypoint próprio e tools. Trocar por detecção
estrutural (presença de `src/server.ts` / `src/tools/index.ts`, ou de manifesto).

**Por quê:** qualquer número extraído de `mcp-tools-audit.json` **subestima a frota real**.
Nenhum documento deve tratar esse arquivo como censo completo.

### B17 · Corrigir ou aposentar o gate de Definition of Done

`scripts/check_mcp_dod.py:30-44,302,326`.

Executado no HEAD, a saída é `"Resumo (MCPs migrados): 1/1 passaram, 0 falharam.
Pendentes de migracao (nao avaliados): 21."` com exit 0. Ele classifica um MCP como
"migrado" pela presença de `BearerAuthMiddleware` **ou** `mount_lowlevel_streamable_http`;
**nenhum** dos 21 servidores contém qualquer um dos dois — todos caem no ramo "legado →
pendente (não derruba o gate)". Pior: o padrão que ele impõe foi declarado **superseded**
por `docs/MCP_COMPLIANCE.md:22-28`.

**Por quê:** um gate que sempre passa é pior que gate ausente. Consequência colateral:
`shared/mcp_auth.py` virou código morto.

### B18 · Preencher `docs/MCP_COMPLIANCE.md` com status por servidor

`docs/MCP_COMPLIANCE.md:30-43` — checklist de 8 itens com **todas** as caixas desmarcadas
e sem tabela de status.

Levantamento já disponível: 21 dos 26 `*-mcp-server/` têm `gateway/`, `Dockerfile`,
`src/config/settings.py` e `src/server/mcp_server.py`. Não têm: `auth-mcp-server` (é um
Authorization Server, não um MCP), `frontend-pixelfera-mcp-server`, e os 3 governados
(que usam o runtime novo, fora do padrão do checklist).

**Por quê:** não existe hoje nenhum relatório que responda "quem está conforme".

### B19 · Remover os 4 bancos SQLite versionados

`cross-devteam-validators/validators.db`, `devteam-observatory/observatory.db`,
`knowledge-base-mcp/knowledge-base.db`, `quality-gates-system/gates.db`.

Remover do índice e adicionar ao `.gitignore`.

> **Não abrir** `knowledge-base.db` (45 KB, o único com conteúdo) antes de decidir o
> destino do conteúdo em [ROADMAP §15](ROADMAP.md).

**Por quê:** estado de aplicação versionado junto com o código; cada execução local suja
o worktree. Precedente: `e04bbe8` (2026-07-10) já removeu três blobs SQLite.

### B20 · Marcar como superseded os documentos de plano obsoletos

`MCP_CONSOLIDATION_PLAN.md` (plano de maio/2026; **nenhum** dos entregáveis nomeados
existe); `DEVTEAM_ECOSYSTEM_IMPLEMENTATION_ROADMAP.md`; `DEVTEAM_ECOSYSTEM_SUMMARY.md`;
`docs/mcp-consolidation-complete.md` (afirma "All 18 MCP servers… now consolidated" e
lista **18 nomes diferentes** dos 18 do catálogo atual — coincidência numérica perigosa);
`MCP_SERVICE_STANDARD.md` e `MCP_CONSTRUCTION_GUIDE.md` (declarados superseded/deprecated,
mas **sem banner de topo**).

Banner de topo em cada um. A raiz tem ~80 arquivos `.md`/`.txt` de status, handoff e plano
sem índice único que diga qual é vigente.

**Por quê:** risco concreto de agente ou pessoa seguir a norma errada. **Sintoma vivo:**
`docker-compose.pilot.yml:4` diz implementar "a topologia de MCP_SERVICE_STANDARD.md
§4/§10" e o validador de token do gateway em produção
(`mcp-gateway/src/auth/token_validator.py:3`) diz implementar "o padrão descrito em
MCP_SERVICE_STANDARD.md §6/§7" — ambos apontando para um documento superseded.

### B21 · Reconciliar o `HANDOFF_DEVTEAM_MCP.md` com o catálogo

`HANDOFF_DEVTEAM_MCP.md:1-20` vs `README.md:31-32` vs `docs/generated/mcp-catalog.md:16`.

O handoff abre com "Consolidação devteam-mcp (20 backends → 1 server) — **COMPLETA**…
entregue, deployado na HML e provado ponta a ponta ao vivo", 456 tools servidas. O
catálogo versionado diz `experimental` e o README diz que ficou fora por 28% de cobertura.

Escrever uma nota de topo no handoff.

**Por quê:** quem lê o handoff conclui que está feito; quem lê o catálogo conclui que não
subiu.

### B22 · Adicionar ADR-017 e ADR-018 ao asset catalog

`platform-catalog/catalog/assets/adr/` (vai de `adr.001` a `adr.016`).

As **duas únicas ADRs `Accepted`** da série nova — ADR-017 (DevTeam Journey) e ADR-018
(Guardian), que carregam a direção de produto vigente — **não têm asset**. Aproveitar para
resolver `adr.002`, `adr.015` e `adr.016`, hoje com `spec.status: unknown` porque os
markdowns migraram para `platform-infra` e os links ficaram quebrados.

**Por quê:** o ADR-014 modela ADR como asset versionado justamente para não haver esse
drift. E o **ADR-016 é quem define o gate de cobertura ≥80% que hoje trava a promoção do
produto** — está linkado e ausente.

### B23 · Registrar no ADR-018 o adiamento da Fase 3

`ADR-018-DEVTEAM-GUARDIAN.md:97-104`.

Registrar explicitamente o adiamento da Fase 3 real e a renumeração feita pelo handoff.
Ver [ROADMAP §4](ROADMAP.md).

**Por quê:** a fase anotada no próprio ADR como "**O diferencial do produto**" está sem
entrega **e** sem registro de adiamento — quem lê o handoff acha que foi feita.

### B24 · Vendorar ou dar SRI ao axe-core do `check_accessibility`

`devteam-mcp-server/src/domains/qa/tools/browser_tool.py:41` (`_AXE_CDN`).

A tool injeta axe a partir de um CDN em tempo de execução, sem SRI e sem vendoring.

**Por quê:** o resultado do check de acessibilidade muda conforme a rede e conforme o que
o CDN servir; em ambiente sem egress a tool simplesmente não roda.

### B25 · Triar — não corrigir em bloco — as marcações de placeholder e sucesso falso

Entrada: `generated/mcp-tools-audit.json` **após B09**.

As listas `placeholder_tools` (106 na frota), `false_success_tools` (46) e
`destructive_tools` (711) **[HEAD]** vêm de regex e produzem ruído: `destructive_tools`
marca qualquer nome contendo delete/execute; no `frontend-pixelfera` a extração AST
confunde valores de enum (`default`, `error`, `loading`, `pass`, `success`) com nomes de
tool.

**Já verificadas manualmente como honestas** e que devem sair da fila:
`deploy/trigger_workflow` e `run_linter` / `run_security_scan` / `check_dependencies` do
domínio qa.

**Placeholders de fato** citados: `generate_adr`, `generate_c4_diagram`,
`generate_playwright_tests`, `generate_migration`, `calculate_rice_score`.
**Sucesso falso** citados: `deploy`, `merge_pr`, `create_pr`, `clone_repo`, `rollback`,
`request_vm`.

Tratar como **fila de triagem**, não como conjunto de defeitos confirmados.

### B26 · Fechar a assimetria da denylist do `devteam-mcp`

`devteam-mcp-server/src/server/mcp_server.py:81-90` e `manifests/mcps/devteam-mcp.yaml`.

A denylist tem 6 tools de segredo. O manifesto declara **7** `tool_contracts`: 6
correspondem exatamente à denylist e o sétimo — `devteam-infra-request-vm` — **não está
excluído**, e é justamente uma das tools marcadas como sucesso falso. Decidir: excluir ou
corrigir a implementação.

### B27 · Resolver o caminho fantasma do `auth-mcp`

`manifests/mcps/auth-mcp.yaml:11` — `legacy_source_paths` lista `services/auth-mcp-server`,
que **não existe**. A auditoria gera uma entrada fantasma com 0 tools; **[HEAD]** há duas
linhas `auth-mcp` na tabela de superfícies, ambas zeradas. Remover o caminho.

### B28 · Decidir o destino do `frontend-pixelfera-mcp-server`

É o único `*-mcp-server` que permaneceu em TypeScript depois da reescrita para Python de
2026-05-11 e **nunca foi migrado para Model C**. Não aparece no compose, no `.mcp.json`
nem no catálogo de 18 — mas o manifesto do `devteam-mcp` o reivindica como fonte legada.
Auditoria **[HEAD]**: 8 declared / 35 dispatchable / 0 catalog. Remover ou consolidar de
fato.
