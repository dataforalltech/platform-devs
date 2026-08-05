# ROADMAP — o que falta na frota DEVTEAM

> **Escopo:** capacidade de produto. Arquitetura, segurança, variáveis de ambiente,
> topologia e deploy vivem em [INFRA.md](INFRA.md).
> **Companheiros:** [RELEASES.md](RELEASES.md) (o que existe) e [BACKLOG.md](BACKLOG.md) (tarefas).

**Medido em:** `develop` @ `f6ba78f`, 2026-08-05.

Cada item declara o **bloqueio real**, não a intenção. Onde o bloqueio é externo a este
repositório, isso está dito — porque priorizar um item bloqueado fora daqui é desperdício.

**Ordenação:** §1–4 destravam o produto; §5–8 são contrato e catálogo; §9–13 são decisões
pendentes; §14–16 são limpeza estratégica e direção.

---

## 1. Promover `devteam-mcp` de `experimental` para `active`

**É o item que trava o produto inteiro.** Sem ele, os 21 domínios de persona e sistema
não são alcançáveis por ninguém.

**Bloqueio declarado** (`README.md`): "ficou fora do runtime porque a suíte atual comprova
apenas 28% contra o gate de 80%".

**Bloqueio real e medido [HEAD]:** **294** de 451 tools despachaveis sem teste (eram 401
antes do fan-out de testes de 2026-08-05 — ver [BACKLOG B15](BACKLOG.md)); 451 sem
contrato; 451 sem output schema; 451 sem entrada no catálogo; 224 sem input schema;
48 placeholders; 27 que retornam sucesso falso; 409 com nome duplicado entre domínios.

> **O que o fan-out mostrou.** A consolidação não só deixou os testes para trás: em
> `pipeline`, `deploy`, `session` e `infra` o código do agregador **divergiu** do servidor
> legado. A afirmação de que as duas cópias eram byte-a-byte idênticas (§14) vale para os
> outros 17 domínios, não para esses quatro. No `pipeline` a divergência é
> comportamental — os testes legados reprovam contra o agregador —, então o domínio ficou
> inteiro de fora do port.

**Causa raiz verificável:** a consolidação (`203d4a1`, 2026-07-17) copiou tools, models e
db byte-a-byte dos ~20 servidores fonte, mas **não migrou os testes**. Hoje
`devteam-mcp-server/tests/` tem 6 arquivos `test_*.py` para **21 domínios**, contra 8–11
arquivos por servidor legado. O próprio `conftest.py` admite: "Testes de integração
chegam no fan-out da Fase 2/3, por domínio" — nunca escritos.

**Bloqueio secundário:** a regra de promoção exige, para provedor ativo que expõe tools,
auth + tenant + PDP fail-closed + audit + redação + contexto assinado; e
`audit_mcp_tools.py --fail-on-runtime-gaps` reprova tool publicada sem schema, contrato,
teste e documentação. Com 451 tools nessas condições, **promoção em bloco é inviável**.

**Caminho realista** — não é opinião, é a única estrutura compatível com o gate:
promoção **por domínio**, não por servidor. Escolher 1–2 domínios com teste real
(`guardian` e `session` são os únicos cobertos hoje), contratualizar suas tools, dar
output schema e promovê-los. **Requer decidir se o manifesto suporta granularidade por
domínio — hoje não suporta.**

---

## 2. Preencher o contrato das 307 operations do `platform-catalog`

> **✅ Feito em 2026-08-05.** `description` e `contract.inputs` derivados do código em 266
> das 307; `contract.outputs` em 19 (só os provedores governados têm contrato de saída).
> Ver [BACKLOG B13](BACKLOG.md).
>
> **O que o preenchimento revelou:** **37 Operations marcadas `lifecycle: stable` não têm
> tool nenhuma que as implemente** no runtime — o catálogo anunciava capacidade inexistente.
> Foram para `lifecycle: retired`. Outras 4 (`*.status`) têm nome ambíguo entre domínios e
> ficaram intocadas: escolher um domínio ali seria inventar o binding.

**Era a maior razão valor/esforço do roadmap, e não tinha bloqueio externo.**

**O estado anterior:** 307 de 307 operations com `contract.inputs: {}` e
`contract.outputs: {}`; 288 de 307 com `metadata.description` vazia — todas marcadas
`lifecycle: stable`. A camada Operation-first que runbooks e agentes consultam para
**escolher** uma capacidade só carregava o id. Um agente que escolhesse
`development.generate_fastapi_router` não tinha como saber, pelo catálogo, que a tool
devolve um esqueleto com `raise NotImplementedError` — a honestidade que existe no código
(ver [RELEASES §5.8](RELEASES.md)) não chegava a quem seleciona. Hoje chega: a description
da Operation é a da própria tool, e diz "Gera o **scaffold** de um APIRouter FastAPI".

**O que continua aberto no catálogo:**

- **`contract.outputs` em 288 das 307.** Não é omissão deste trabalho: nenhum servidor de
  persona declara output schema, e só os 3 provedores governados têm contrato de saída
  canônico. Preencher exige escrever os contratos, não derivá-los.
- **`selection: {}` em 317/317 tools** e description vazia em 20/23 providers.
- **As 4 `*.status`** ficaram sem contrato por ambiguidade de nome entre domínios.
- **As 37 `retired`** precisam de decisão: apagar do catálogo, ou reimplementar a
  capacidade que elas anunciavam.

---

## 3. Reconciliar o `platform-catalog` com a frota pós-consolidação

**[HEAD]** `catalog/providers/` tem 23 arquivos, **todos de personas legadas**. **Não
existe provider `devteam-mcp`.** Não existe nada de `guardian`.

Os 317 bindings em `catalog/tools/` apontam `spec.provider_id` para os ids legados e
declaram nome de tool **sem prefixo** (`run_security_scan`), enquanto o runtime real é
`POST /mcp/tools/call` no `devteam-mcp` com nomes **prefixados por domínio**
(`qa_run_security_scan`). **Nenhum dos 317 bindings resolve contra o runtime da frota** —
é por isso que a auditoria reporta `catalog_tools = 0` para o `devteam-mcp`.

Pior: `manifests/mcps/devteam-mcp.yaml` aponta `tool_catalog` para esse catálogo
desatualizado.

**Bloqueio:** nenhum externo. Depende de decidir se o modelo de provider passa a ser
por-domínio-dentro-do-`devteam-mcp` ou um provider único.

---

## 4. ADR-018 Fase 3 — "o diferencial do produto" não existe

O faseamento do ADR-018 é: (1) núcleo versionado, (2) corpo tipado e relações,
(3) **escopo por projeto e adoção** — anotada literalmente no ADR como
**"O diferencial do produto"** —, (4) guardião ativo.

**[HEAD], por grep no domínio guardian inteiro:** `gov_adoption`, `gov_project_override`,
`gov_check`, `gov_gate_result`, `gov_requirement`, `apply_standard`, `resolve_effective`,
`record_check_result`, `non_waivable` — **todos com zero ocorrências**.

O handoff **renumerou as fases**: chamou de "Fase 3" o que o ADR chama de Fase 4 parcial
(conformance + waivers, entregue). A Fase 3 real ficou **sem entrega e sem registro de
adiamento** — quem lê o handoff conclui que foi feita.

**Bloqueio:** nenhum. É trabalho não feito, sem justificativa registrada.

---

## 5. ADR-018 D18.8 — requisito tipado não existe

D18.8 exige requisito com identidade em dois níveis (`requirement_uid` estável mais linha
por `(directive_uid, version, req_code)`). Nada disso existe. O guardião registra a
**diretriz** mas não o **requisito** — que é justamente a unidade que conformance, waiver
e check deveriam referenciar. Hoje `gov_conformance_control` se ancora num `control_id`
livre, com `directive_uid` opcional.

**Bloqueio:** depende do §4 estar decidido — requisito é a chave de junção de
adoção/override.

---

## 6. ADR-018 D18.10 — paridade dura não atingida

D18.10 fixa como critério de aceite duro "`guardian_validate_hub` vs `validate_hub.py` no
mesmo commit = zero divergência" **antes** de o banco virar fonte da verdade. O único
import real registrado (84 diretivas, 80 relações) terminou com **2 erros de persistência
e 7 de parse**. Não é paridade zero — portanto o hub markdown **não pode virar read-only
ainda**.

**Bloqueio externo:** `validate_hub.py` vive em `private-libs/platform-service-template`,
fora desta árvore. Não é verificável nem corrigível daqui.

---

## 7. ADR-017 Fatia C — resolução de repositórios por `project_id`

Parcial. `setup_project_workspace` recebe a lista de repositórios do **chamador** em vez
de resolver por `project_id`, com `TODO(D17.7/G9)` explícito no código.

**Bloqueio duplo:** (a) `platform-connectors` não expõe `resolve_repo_clone()` — "será
implementado lá", não existe; (b) `project-product-mcp` não está registrado no gateway
(item G9 pendente).

**Efeito hoje:** `session_bootstrap` devolve `credential_status='deferred'` e
`workspace_status='deferred'`.

**Desbloqueio único identificado:** corrigir o 401 de S2S no `platform-connectors`
resolve esta fatia **e** a de credenciais de uma vez. O lado de credencial está em
[INFRA §10](INFRA.md).

---

## 8. ADR-017 Fatia D — bridge executor→journal

Não começou.

**Bloqueio externo:** é do repositório `platform-devs-agent`, para onde o runtime do
agente saiu em 2026-07-14/16. **Fora do escopo deste repo.**

---

## 9. `dev-twin.authenticate` desconectado de `session_bootstrap`

Achado registrado em 2026-07-22, não endereçado. Nada em `session_tool.py` chama
`dev-twin.authenticate` e nada em `auth_tool.py` referencia `session_bootstrap`. São dois
fluxos paralelos: o bootstrap cria a sessão **sem verificar se o cliente está autenticado**,
e a ordem "autentica → depois bootstrap" fica a cargo do cliente (`dftunnel`), não é
imposta pelo servidor.

**Bloqueio:** decisão de produto sobre **quem impõe a ordem**. Não é bug fechado, é
fiação pendente.

---

## 10. Lacunas de catálogo da Wave-1

Fonte: `docs/catalog-gaps/runbooks-wave1.md`.

**10a. Leitura estruturada de ADR.** Existe `governance.create_adr` (escrita) e **nenhuma
operation de leitura**. Candidatas: `governance.list_adrs`, `governance.get_adr`. Enquanto
não existirem, a runbook `architecture_review` **omite o passo de puxar os ADRs regentes**
e valida o desenho apenas contra metadados de serviço e grafo de ecossistema. Nenhum dos
13 domínios de operation tem leitura de ADR. *Bloqueio: nenhum.*

**10b. Ciclo de vida de incidente.** Não existe domínio `incident`. Candidatas:
`incident.declare`, `incident.update_status`, `incident.resolve`. Hoje a runbook cobre
detectar→diagnosticar→mitigar→verificar, mas **o registro do incidente é omitido**.
*Bloqueio: casa exatamente com `incident-response-mcp` estar `planned` — a lacuna de
catálogo e a de runtime são a mesma peça faltando.*

**10c. Paginação de on-call e comunicação de status.** Candidatas:
`communication.page_on_call`, `communication.post_status`. *Bloqueio: por ADR-009 vivem
num gateway separado (`platform-communication`) ainda não federado neste catálogo — é
lacuna de **federação**, não capacidade a inventar localmente.* **Efeito de produto: a
runbook de incidente entregue hoje não paga ninguém.**

---

## 11. Os 8 MCPs `planned` — nome reservado, escopo não especificado

`database-ops`, `developer-environment`, `event-ops`, `execution-sandbox`,
`feature-flags`, `incident-response`, `observability`, `workflow-orchestrator`.

Cada um tem um manifesto de ~15 linhas com `runtime.mode: none` e uma descrição de uma
linha ("catalog only"). **Nenhum tem spec, escopo dimensionado ou dono designado.**

Tratá-los como roadmap comprometido seria falso. São **intenção declarada**. O primeiro
trabalho de qualquer um deles é escrever a spec, não o código.

Exceção com sinal claro: `incident-response-mcp` é o único cuja falta já tem consequência
medida hoje (§10b).

---

## 12. Decidir o destino do `cache-mcp`

**Este item foi reclassificado.** A leitura inicial — "código completo, basta ligar o
transporte" — não sobrevive à verificação. Ver [RELEASES §5.5](RELEASES.md).

Três bloqueios reais, não um:

1. **O entrypoint não inicia.** `main()` chama `server.run()` com aridade e tipos errados
   → `TypeError` no boot. Nenhum teste toca `main()`.
2. **Não há superfície HTTP nenhuma** no código, embora o manifesto declare `http: true`
   com `canonical_http`.
3. As 7 tools são proxies para uma API `platform-cache` **que não existe** neste repo nem
   em compose nenhum. Somam-se 7/7 sem output schema, contrato, catálogo, authorization,
   tenant e audit.

**A decisão continua binária — extinguir ou reativar —, mas o custo de reativar é
escrever um servidor Model C do zero.** Enquanto ficar no limbo, consome atenção em toda
varredura de conformidade sem entregar nada.

---

## 13. Promoção dos 3 experimentais externos

`auth-mcp`, `connectors-mcp`, `scheduler-mcp`: `runtime.mode: external`,
`ci.enabled: false`, gateway e registry desligados.

**Bloqueio: o caminho para `active` não passa por este repositório.** O plano de controle
instrui a promover provedores experimentais individualmente, **após testes de contrato no
repositório proprietário** (`dataforalltech/platform-auth`, `/platform-connectors`,
`/platform-scheduler`). O README acrescenta que ficam fora "até comprovarem o contrato de
contexto assinado e tenant derivado".

**Caso específico do `auth-mcp`:** o que existe em `auth-mcp-server/` **não é o MCP** —
são `authorization_server.py` e `oidc_upstream.py`, um Authorization Server OAuth, sem
`pyproject.toml` e sem Dockerfile próprio. **Não há nada a promover daqui.**

**Consequência de produto já assumida:** as tools mais críticas desses provedores já têm
contrato escrito e estão **deliberadamente fora do runtime** — SQL ad-hoc, drop e truncate
do connectors (críticos, N2) e `execute_scheduler` (alto risco, N2).

---

## 14. Fechar o strangler — aposentar os ~20 servidores legados

O commit de fan-out (`203d4a1`, 2026-07-17) declarava a pendência textualmente: "Falta:
assemble, build image + deploy strangler + prova no gateway, **aposentar os 20**". As três
primeiras foram feitas em 17-18/07. **A quarta nunca.**

Existem 26 diretórios `*-mcp-server` na raiz, dos quais ~20 são as fontes legadas, todas
com código e testes próprios, **duplicando** os 21 domínios de `devteam-mcp-server/src/domains/`.
`diff -rq` entre um servidor legado e o domínio correspondente acusa **só o
`__init__.py`** em 17 dos 21 domínios — o conteúdo de `tools/`, `checkers/` e `db/` é
idêntico neles. **Quatro divergiram**, e a medição corrige o que este documento afirmava
antes: `deploy` (7 arquivos), `session` (5), `pipeline` (4) e `infra` (2). No `pipeline` a
divergência é comportamental, vinda do ledger fail-closed de 2026-08-03.

Eles continuam recebendo manutenção: a correção do bootstrap de segredos de 2026-08-05
tocou os 21 servidores legados, **não o agregador**.

**Consequência:** custo de manutenção dobrado e risco de divergência silenciosa. O bug do
`SecurityChecker` ([BACKLOG B01](BACKLOG.md)) existe nas **duas** cópias.

**Bloqueio:** depende do §1 — o `devteam-mcp` precisa estar `active` antes de aposentar as
fontes.

---

## 15. Resolver os 4 sistemas TypeScript órfãos

`knowledge-base-mcp`, `cross-devteam-validators`, `quality-gates-system`,
`devteam-observatory`. Prometidos em `DEVTEAM_ECOSYSTEM_IMPLEMENTATION_ROADMAP.md`
(5 semanas, com deliverables e métricas) e **desmarcados** no checklist do
`DEVTEAM_ECOSYSTEM_SUMMARY.md`. Existem como stubs que afirmam falsidade
([RELEASES §5.2](RELEASES.md)). Sem manifesto, fora dos 18, fora do compose, **com `.db`
versionado**. Nem sequer estão como `planned`.

**Decisão necessária, três opções mutuamente exclusivas:**

- **(a) apagar** — o store SQLite implementado se perde, mas nada é usado hoje;
- **(b) reescrever** contra o store que já existe e consolidar como domínios do
  `devteam-mcp`;
- **(c) declarar `planned`** e parar de exibi-los como se existissem.

**Bloqueio:** nenhum técnico. É decisão de produto não tomada.

---

## 16. A linha estratégica não decidida que trava 12 ADRs

**ADR-003 a ADR-014 — 12 decisões, todas datadas 2026-07-05 — estão em `Proposed`.**

`MCP_ADR_INDEX.md` declara o que falta para decidir:

1. **A escolha estratégica "plataforma interna × produto comercial"**, que define a
   prioridade do ADR-008 (North-Star).
2. O sign-off dos donos de `platform-auth` + `platform-governance` + `platform-admin`
   sobre **quem assina o Twin Token no fim**, com sunset explícito do auth-mcp-STS.

Isto separa nitidamente **decisão tomada e pendente de execução** (ADR-001, 017, 018 =
`Accepted`) de **intenção ainda não decidida** (003–014). Nenhum item do roadmap acima
que dependa da série 003–014 deve ser planejado antes dessa escolha.

### As 4 perguntas em aberto do ADR-017

1. Env vars e `REPOS_ROOT` ficam no store do domínio `config`, ou a regra de credencial se
   estende a qualquer variável com segredo?
2. O `config-mcp-server` standalone ainda é deployado, ou foi superado pelo domínio
   `config` consolidado?
3. Árvore de trabalho **flat** (`REPOS_ROOT/<repo>`) ou **aninhada por projeto**
   (`REPOS_ROOT/<project>/<repo>`)?
4. Qual o contrato exato do payload de ambiente que o cliente/tunnel envia ao
   `session_bootstrap`?

**As perguntas (3) e (4) amarram o contrato do onboarding** — são as que mais custam a
adiar.
