# Handoff — ADR-018 Guardian, Fase 1 até Fase 3 + matriz de rastreabilidade (concluídas, mergeadas, VALIDADAS contra MySQL real)

**Data:** 2026-07-22
**Branches mergeadas em `platform-devs`:** `feat/guardian-domain`,
`feat/guardian-hub-importer`, `feat/guardian-lcr-schema`,
`feat/guardian-fase2-sections-relations`, `feat/guardian-traceability-matrix`,
`feat/guardian-fase3-conformance-waivers` → `develop` (local + remoto, todas
deletadas).
**Branch mergeada em `privates-libs/platform-database-lib`:**
`fix/unit-of-work-mysql-returning-v2` → `develop` (repo separado, ver seção própria).
**Commits (platform-devs):** `6d238e7` (fix deploy) → `bc8ac46` (feat guardian Fase 1) →
merge `8eff2bb` → docs `5510b6c`/`29558b0` → `6f0271b` (Fase 1b importador) → merge
`b7a8dd8` → docs `45781b9` → `603415e` (Fase 1c LCR/handoffs/specs) → merge `c6a1ba2` →
docs `f5f6811` → `6cf871f` (Fase 2 seções/relações/archetype) → merge `e5303ca` →
`f8172c0` (parser da matriz de rastreabilidade) → merge `0644493` → docs `d671edb` →
`6af5b16` (Fase 3 conformance/waivers) → merge `28a2c05`.

## O que foi feito

1. **ADR-018-DEVTEAM-GUARDIAN.md** (commit anterior `7cc227e`, já na develop) — desenho do
   domínio `guardian`: DevTeam como guardião das diretrizes (princípios → ADR → standards →
   arquitetura de referência → runbooks), rejeitando JSON-blob, com identidade imutável
   (`directive_uid`) e revisões append-only.

2. **Domínio `guardian` Fase 1** implementado em
   `devteam-mcp-server/src/domains/guardian/`:
   - `models.py` — 4 modelos Pydantic (`GovKindCapabilityRow`, `GovStatusVocabRow`,
     `GovDirectiveRow`, `GovDirectiveVersionRow`).
   - `db/schema.py` — DDL das 4 tabelas via `create_table_from_model` + UNIQUE por chave
     natural, `ensure_schema` idempotente dual-engine.
   - `db/store.py` — `GuardianStore`: seed de referência (12 kinds, 7 status), CRUD
     versionado (`create_directive`, `get_directive`, `list_directives`,
     `update_directive`, `set_directive_status`, `supersede_directive`), invariante
     "exatamente uma versão vigente por uid" via `transaction()`.
   - `catalog.py` + `plugin.py` — 9 tools prefixadas `guardian_<op>`, auto-descobertas
     pelo agregador (`src/domains/DOMAINS`, sem edição manual de registry).
   - `tests/test_guardian.py` — 12 testes de integração (mesmo harness de
     `test_session_journey.py`), banco MySQL real, skip automático sem
     `MYSQL_ROOT_PASSWORD`.

3. **Fix de regressão colateral encontrada durante a verificação:** o domínio `deploy`
   (24→31 tools, inclui `sync_repo` da Fatia C do ADR-017) estava sendo **pulado
   silenciosamente** pelo auto-discovery do agregador — `catalog.py` importava
   `sync_repo` de `.tools`, mas `tools/__init__.py` nunca o reexportava. O
   `ImportError` era engolido e só logado como `warning`, então o domínio inteiro
   (não só a tool nova) desaparecia do agregador sem qualquer teste vermelho.
   Corrigido em `devteam-mcp-server/src/domains/deploy/tools/__init__.py`
   (commit `6d238e7`). Confirmado via import sanity: domínios registrados foram de
   20 → 21 após o fix.

## Validação feita (agora completa, contra MySQL 8.4 real)

- ✅ `ruff check` / `black --check` / `mypy` limpos (7 arquivos do domínio guardian).
- ✅ Import sanity: `plugin.register()` do guardian retorna 9 schemas corretos
  (capability `devteam-mcp.guardian_<op>`, required_scope `guardian:<res>:<ação>`,
  data_domain `governance`); auto-discovery confirma `guardian` e `deploy` presentes
  em `src.domains.DOMAINS` (21 domínios totais).
- ✅ **12/12** `tests/test_guardian.py` verdes contra MySQL 8.4 real.
- ✅ **13/13** `tests/test_aggregator.py` verdes (nenhuma colisão de tool-name).
- ✅ **9/9** `tests/test_session_journey.py` + `tests/test_sync_repo.py` verdes
  (confirma que o domínio guardian e o fix do deploy não regrediram nada existente).

O Docker Desktop não subia no início da sessão (engine travava na inicialização do
WSL); depois de reiniciar o SO ele voltou a subir normalmente. A senha do MySQL
compartilhado (`dataforall-tenant-mysql`) estava com drift entre o `.env` atual e o
volume persistido (mesmo padrão de outras sessões — env muda, volume não), então os
testes rodaram contra um **container MySQL 8.4 descartável** (`docker run` avulso,
porta separada, removido ao final) — o MySQL compartilhado nunca foi tocado/sujado.

### 3 bugs reais achados e corrigidos rodando contra MySQL de verdade

Nenhum deles aparecia em ruff/black/mypy — só se manifestavam em runtime contra MySQL:

1. **`seed_reference_data`**: `Repository.upsert()` exige `conflict_columns` como
   argumento posicional — faltava nas duas chamadas (kind/code). `TypeError` imediato.
2. **`update_directive`**: o `insert` da nova versão dentro de `transaction()` pedia
   `RETURNING id` por padrão. Achado: `UnitOfWork.fetch_one` (o pool usado dentro de
   `transaction()`) **não emula `RETURNING` no MySQL** como o pool top-level faz — o
   SQL ia literal pro driver e quebrava com syntax error. Isto é um gap real da lib
   `platform_database` (`unit_of_work.py`), não só do guardian — qualquer domínio que
   faça `insert()` dentro de uma `transaction()` no MySQL vai bater nisto. Fix local:
   `returning=None` (o guardian não precisa do id ali). **Vale abrir um item para
   corrigir isso na própria `platform_database` depois** (fora do escopo desta sessão).
3. **Normalização de bool**: colunas TINYINT (`is_current`, `allows_rfc2119`,
   `allows_fileline`, `is_terminal`) voltavam como `int` (0/1) do driver MySQL, não
   `bool` — a API do guardian devolvia `1` em vez de `True`. Corrigido normalizando
   essas chaves em `_jsonable`.

## Fase 1b — importador markdown→DB do hub (concluída, escopo reduzido e documentado)

Pesquisa prévia (agente Explore lendo `platform-service-template/scripts/validate_hub.py`
+ estrutura real do hub) revelou que o hub é bem mais rico que o schema da Fase 1: 3
vocabulários de status distintos por família de documento, campos de gestão de mudança
específicos de LCR sem coluna equivalente, relações `governado_por`/matriz N:N:N:N não
modeladas, IDs com convenção de nome de arquivo variável por camada (e um caso de
colisão real: `decisions/adr-0001.md` vs `adr/0001-*.md` usam o mesmo número mas são
documentos DIFERENTES). Decisão: implementar um recorte **honesto** da Fase 1b em vez de
prometer paridade total — documentado explicitamente no código, não só aqui.

**Implementado** (`devteam-mcp-server/src/domains/guardian/importer.py` + extensões em
`db/store.py`/`catalog.py`):
- Importa as **7 camadas estruturadas** com front-matter uniformemente obrigatório:
  `principles/adr/standards/reference-architecture/runbooks/it/decisions`.
- `directive_uid` derivado do NOME DO ARQUIVO por convenção de camada (mais estável que
  o front-matter, que nem sempre tem um campo de id explícito). `decisions/adr-000N.md`
  vira `PLATFORM-ADR-000N` — namespace próprio para não colidir com `adr/000N-*.md`.
- Título: front-matter `title` se existir, senão primeiro H1 do corpo.
- Corpo: heurística de split em `body_context`/`body_decision` pelo primeiro heading de
  decisão (`## Decisão`/`## Decision`/`## MUST`) — sem heading correspondente, tudo vira
  `body_context` (nada se perde). A divisão por seção tipada de verdade é Fase 2.
- Status: alias `vigente`→`aceito` (drift real visto em runbooks); `STATUS_VOCAB` da
  Fase 1 ganhou `historico-substituido` (existia no hub real, faltava no vocabulário).
- `GuardianStore.import_directive` — idempotente: cria se novo, versiona (append-only)
  se o conteúdo mudou, no-op se está igual; sinaliza (sem aplicar) `kind_scope_mismatch`
  se um reimport trouxer kind/scope diferente do cabeçalho já persistido.
- `GuardianStore.diff_hub` — diretivas `scope=platform` no DB que não aparecem no
  conjunto importado (candidatas a órfã/retirada).
- 2 tools novas: `guardian_import_hub` (escreve) e `guardian_validate_hub` (dry-run:
  reporta drift — criaria/atualizaria/órfãs/erros de parsing — SEM persistir nada).
- **26/26 testes verdes contra MySQL 8.4 real** (12 Fase 1 + 4 integração import/validate
  + 10 unitários do parser em `tmp_path`, sem depender do repo `platform-service-template`
  estar clonado no ambiente).

**Deliberadamente FORA de escopo nesta fase** (LCR/handoffs/specs foram cobertos
depois, na Fase 1c — ver abaixo):
- Relações `governado_por` e a matriz de rastreabilidade N:N:N:N de
  `documentation-model.md` — exige uma tabela de arestas tipadas
  (`gov_directive_reference(from_uid, to_uid, relation_type)`), fora do núcleo
  versionado da Fase 1 — **Fase 2**.
- Paridade completa com `scripts/validate_hub.py` (templates YAML/K8s/Istio, Statement
  of Applicability, "semantic currentness", segurança de `.mcp.json`) — esse script
  cobre superfícies de infra/segurança que não são responsabilidade do guardian
  ("registry+policy, NÃO executor" — D18); `guardian_validate_hub` cobre só drift de
  governança documental (filesystem × `gov_directive`/`gov_directive_version`).

## Fase 1c — schema LCR/handoffs/specs + status kind-scoped (concluída)

Cobre as 3 camadas que a Fase 1b deixou de fora por terem front-matter heterogêneo
(sem convenção estrutural uniforme imposta pelo `validate_hub.py` do template):

- **`GovLcrDetailRow`** (nova tabela `gov_lcr_detail`, 1:1 por `directive_uid`) —
  metadados de gestão de mudança do Library Change Request sem equivalente no núcleo
  versionado: `biblioteca`, `repositorio`, `versao_atual`, `versao_alvo`, `tipo`
  (patch/minor/major), `breaking`, `urgencia`, `aprovador`, `solicitante`, `achado`
  (ref a control id de auditoria), `data_solicitacao` (imutável).
- **`GovLcrSubstitutionRow`** (nova tabela `gov_lcr_substitution`) — a aresta
  `substituido_por` do LCR é uma LISTA no front-matter; normalizada em uma linha por
  alvo (rejeição de JSON-blob, D18.2), não serializada numa coluna.
- **Status kind-scoped, de verdade agora**: `STATUS_VOCAB` ganhou 4 códigos com
  `applies_to_kind='lib_change_request'` (`pendente-aprovacao`/`aprovado`/
  `implementado`/`bloqueado-dependencia-externa`) — o vocabulário próprio do LCR,
  distinto do vocabulário normativo de diretriz. A coluna `applies_to_kind` já
  existia desde a Fase 1 mas **não era enforced** — `_validate()` agora rejeita, por
  exemplo, `status='pendente-aprovacao'` numa diretriz `kind='standard'`.
  `update_directive`/`set_directive_status` passaram a validar contra o kind também
  (antes só `create_directive` validava).
- **Importer**: `directive_uid` para `lib-change-requests/`, `handoffs/`, `specs/` é
  o **stem inteiro do arquivo** (sem regex de convenção) — achado real: LCR permite
  números duplicados com slugs diferentes (dois arquivos `LCR-005-*` coexistindo com
  assuntos distintos), então usar só o prefixo numérico colidiria. Status de
  handoffs/specs tem fallback `"aceito"` quando ausente (heurística documentada, não
  uma convenção confirmada do hub).
- 3 tools novas: `guardian_set_lcr_detail`, `guardian_get_lcr_detail`,
  `guardian_list_lcr_substitutions`. `import_hub`/`validate_hub` agora cobrem as 10
  camadas (7 da Fase 1b + 3 da Fase 1c) — LCR sincroniza detail+substituições junto
  com a diretriz.
- **37/37 testes verdes contra MySQL 8.4 real** (26 de Fase 1+1b + 11 novos: detail
  idempotente, substituições idempotentes, kind-scoping aceito/rejeitado, sync via
  import_hub) + 16 unitários do importer (LCR/handoffs/specs incluídos).

## Fix na `platform-database-lib` (repo separado — concluído)

Achado durante a validação da Fase 1: `UnitOfWork.fetch_one`/`fetchval` (usados
dentro de `Repository.transaction()`) **não emulavam `RETURNING` no MySQL** como o
`MySQLPool` top-level faz — qualquer `insert()`/`upsert()` com `returning` não-None
chamado dentro de uma transação quebrava com `ProgrammingError` (MySQL não tem
`RETURNING`). Corrigido em
`privates-libs/platform-database-lib/src/platform_database/unit_of_work.py`: os dois
métodos agora detectam a cláusula e replicam a emulação do pool (INSERT→lastrowid/PK;
UPDATE→WHERE original) **na mesma conexão da transação, sem commit intermediário**
(committar no meio quebraria a atomicidade que `transaction()` promete). 3 testes de
regressão novos (`tests/test_unit_of_work_returning.py`), 271/271 verdes na suíte
completa da lib. Mergeado em `develop` desse repo (commit `5243c03`).

⚠️ **O `platform-devs` ainda usa o workaround `returning=None`** em
`store.py::update_directive` — o fix da lib não foi revertido do guardian porque a
dependência do `platform-devs` é pinada numa tag/versão específica (não uma branch),
e a lib corrigida ainda não foi tagueada/lançada. Quando uma nova versão da
`platform-database-lib` for adotada, dá pra remover o `returning=None` e deixar
`update_directive` usar `RETURNING id` normalmente (não é urgente — o workaround
funciona, é só um comentário de código a mais).

**Cuidado ao trabalhar em `privates-libs/platform-database-lib`:** o `.git/config`
desse repo só tem fetch refspec para `main` (`+refs/heads/main:refs/remotes/origin/main`)
— um `git fetch origin <branch>` popula `FETCH_HEAD` mas NÃO atualiza
`refs/remotes/origin/<branch>` corretamente, então `origin/develop` local fica
silenciosamente desatualizado. Use `git fetch origin` (sem refspec restrito) ou
`git fetch origin +refs/heads/develop:refs/remotes/origin/develop` explicitamente, ou
confirme via `gh api repos/.../branches/develop --jq '.commit.sha'` antes de basear
qualquer branch nova.

## Fase 2 — corpo tipado por seção, relações governado_por/matriz, escopo archetype (concluída)

As 3 frentes que ficaram deliberadamente de fora até aqui:

- **`GovDirectiveSectionRow`** (nova tabela `gov_directive_section`, chave natural
  `(directive_uid, version, order_index)`) — uma linha por heading `##` do corpo
  original, versionada junto com `gov_directive_version`. Complementa (não substitui)
  `body_context`/`body_decision` da Fase 1 — aqueles continuam existindo. `order_index`
  (não `section_key`) é o desambiguador porque headings podem se repetir.
- **`GovDirectiveRelationRow`** (nova tabela `gov_directive_relation`, chave natural
  `(from_uid, to_ref, relation_type)`) — aresta tipada que cobre uniformemente o campo
  `governado_por` (it/decisions/LCR → standard/ADR) E a matriz de rastreabilidade de
  `documentation-model.md` (vocabulário: `governed_by` + 4 `traces_to_*`). `to_ref` é
  referência FRACA (pode ser externo ao guardian).
- **Escopo `archetype` ativado de verdade**: `SCOPE_RANK` ganhou `archetype: 2` (era só
  reservado, colapsado em `platform` na Fase 1); `gov_directive` ganhou `archetype_ref`
  (backfill idempotente via `AddColumn`, mesmo padrão do domínio `session`) — obrigatória
  sse `scope='archetype'`, mesma validação de `project_ref`.
- **Importer**: parsing genérico de seções por heading `##` (qualquer kind, sem
  hardcoding por camada — cobre ADR/Standard/Princípio/IT/Runbook uniformemente) +
  extração de `governado_por` do front-matter (lista YAML OU string `"STD-A, STD-B"`
  separada por vírgula) — ambos sincronizados via `import_hub` para qualquer camada,
  não só LCR.
- 5 tools novas: `guardian_replace_sections`, `guardian_list_sections`,
  `guardian_add_relation`, `guardian_list_relations`, `guardian_remove_relation`.
- **Bug real achado rodando contra MySQL**: `replace_sections` tentava um "full
  replace" via `delete_where()` + insert dentro de `transaction()` — mas
  `Repository.delete_where` é **soft-delete** (`UPDATE excluded=1`), e o MySQL não tem
  índice único parcial, então a linha "excluída" continuava colidindo com a constraint
  UNIQUE ao reinserir a mesma chave natural (`IntegrityError 1062`). Redesenhado para
  **upsert puro** por `(directive_uid, version, order_index)` — sem delete físico
  (mesmo princípio de D18.8: nunca soft-deletar uma chave natural reaproveitável).
  **Limitação documentada** (não escondida): reimportar com MENOS seções não remove o
  `order_index` extra da rodada anterior — fica com conteúdo antigo até ser
  sobrescrito, não desaparece silenciosamente. Aceitável porque `body_context`/
  `body_decision` continuam sendo a fonte de verdade completa; seções são conveniência
  de leitura, não uma segunda fonte de verdade.
- **48/48 testes verdes contra MySQL 8.4 real** (37 de Fase 1+1b+1c + 11 novos:
  archetype scope, seções upsert-in-place, relações idempotentes, kind-scoping,
  rejeição de relation_type desconhecido, sync via import_hub) + 21 unitários do
  importer (seções + governado_por incluídos).

## Parser da matriz de rastreabilidade central (documentation-model.md) — concluído

Fechava a última pendência explícita da Fase 2: a tabela de arestas
(`gov_directive_relation`) já existia, faltava o parser que lê especificamente esse
arquivo central (formato de tabela markdown, diferente do front-matter por-documento
que `scan_hub` já cobre via `governado_por`).

- `importer.parse_traceability_matrix(model_text)` — parsing puro (sem I/O). Acha a
  seção "## Mapa de rastreabilidade" (por substring de heading, tolerante a variação
  de texto) e extrai a tabela; casa colunas por substring do header
  (Princípio/Standard/Reference/Runbook → `relation_type` `traces_to_*`), não por
  posição fixa. Remove anotações `*(...)*` token a token (mesmo regex de
  `validate_hub.py`). Linhas cujo primeiro campo não bate com `\d{4}` no início (ex.
  "MCP Gateway †" — referência externa citada por prosa, sem ADR local) são puladas
  sem erro, coletadas em `skipped_rows`. Também extrai a seção "## Fora da matriz"
  (exceções documentadas) para relatório — não vira relação, só é reportada.
- Tool nova: `guardian_import_traceability_matrix(model_path)` — parseia e persiste
  via `store.add_relation` (já existente da Fase 2).
- **Validado contra o arquivo REAL** do `platform-service-template`
  (`docs/documentation-model.md`, disponível localmente neste ambiente) — não só
  fixture sintética: 80 relações extraídas corretamente, "MCP Gateway †" pulado,
  as anotações complexas do ADR-0018 (`*(retirado — D1)*`, `*(LAB retirado)*` em 3
  células diferentes) stripadas certo por token, exceção `STD-GW-001` capturada. O
  teste que roda contra o arquivo real é `skipif` gracioso quando o repo
  `platform-service-template` não está clonado ao lado (não quebra CI em outros
  ambientes).
- **55/55 testes verdes** no domínio guardian (48 de Fase 1+1b+1c+2 + 7 novos:
  extração por coluna, stripping de anotação, skip de linha não-numérica, exceções,
  seções ausentes, persistência via catalog) + 13/13 aggregator sem regressão.

## Fase 3 — conformance controls + waivers (concluída, escopo reduzido por decisão explícita)

Decisão tomada com o usuário antes de implementar (a pergunta certa: "Fases 3-4" nunca
tinham desenho real, só uma menção apontando pros 4 YAMLs do template): modelar
**apenas** conformidade e waivers — `service-profile`/`authorization-policy`/
`network-policy` ficam **fora do guardian de vez**, são configuração de infra/deploy de
um serviço (runtime, exposição, portas, políticas de rede), território que já pertence
aos domínios `devops`/`deploy`/`security` do devteam-mcp, não à identidade de "guardião
das diretrizes". Conformidade é diferente: é genuinamente rastrear se um projeto está
em dia com o que o guardian já registra.

- **`GovConformanceControlRow`** (nova tabela `gov_conformance_control`, chave natural
  `(project_ref, control_id)`) — inspirada em `service-conformance.yaml.template`, mas
  persistida/consultável em vez de um arquivo YAML solto por serviço. `status` tem
  vocabulário PRÓPRIO (`CONFORMANCE_STATUS`: blocked/fail/not_applicable/
  not_assessed/partial/pass — **não** é o mesmo vocabulário de `STATUS_VOCAB` da
  diretriz), com enforcement de verdade: `evidence` obrigatório sse `status='pass'`,
  `reason` obrigatório para qualquer outro status (mesma regra do
  `validate_hub.py` do template, "summary deve bater com a contagem por status" virou
  `conformance_summary()` calculado ao vivo em vez de um campo que pode divergir).
  `directive_uid` é opcional — nem todo control deriva de uma diretriz já registrada.
- **`GovWaiverRow`** (nova tabela `gov_waiver`, chave natural
  `(project_ref, control_id, expires_on)`) — exceção temporária **sempre** com validade
  e justificativa, nunca uma isenção permanente silenciosa. Renovar com validade
  DIFERENTE cria um novo registro (histórico natural de renovações); a mesma validade
  reenviada é idempotente. `status` do waiver (`active`/`expired`/`revoked`) é
  independente do `CONFORMANCE_STATUS` do control — `expire_waiver`/`revoke_waiver` são
  marcações EXPLÍCITAS, esta fase **não** calcula expiração automaticamente a partir de
  `expires_on` na leitura (simplificação deliberada e documentada — um job futuro
  poderia fazer isso, não existe hoje).
- 8 tools novas: `guardian_set_conformance_control`/`get_conformance_control`/
  `list_conformance_controls`/`conformance_summary`, `guardian_create_waiver`/
  `list_waivers`/`revoke_waiver`/`expire_waiver`.
- **62/62 testes verdes** no domínio guardian (55 anteriores + 14 novos: evidence/reason
  obrigatórios por status, upsert de reassessment, summary por contagem, idempotência
  de waiver, renovação com validade diferente cria 2º registro, revoke/expire,
  roteamento via catalog) + 13/13 aggregator sem regressão.

## Fora de escopo mesmo depois de tudo isso

- `service-profile`/`authorization-policy`/`network-policy` — decisão EXPLÍCITA de não
  modelar no guardian (ver Fase 3 acima); se algum dia fizer sentido, é mais provável
  que pertençam a uma extensão dos domínios `devops`/`deploy`/`security` já existentes.
- "Índice por capacidade" (a 3ª tabela de `documentation-model.md`, complementar ao
  mapa por-ADR) não foi parseada — é redundante com a matriz principal (aponta de
  volta pras mesmas linhas), então não parecia agregar valor extra além do que
  `parse_traceability_matrix` já extrai.
- Cálculo automático de expiração de waiver (hoje é marcação explícita via
  `expire_waiver`, não recalculado a cada leitura de `expires_on`).

## Arquivos-chave para retomar

- `ADR-018-DEVTEAM-GUARDIAN.md` — decisões D18.1-D18.10.
- `devteam-mcp-server/src/domains/guardian/` — Fase 1 até Fase 3 + matriz de
  rastreabilidade completas, validadas contra MySQL real e contra o arquivo real do
  template (`db/store.py`, `catalog.py`, `importer.py`, `models.py`, `db/schema.py`).
- `devteam-mcp-server/tests/test_guardian.py` + `test_guardian_importer.py` — 62/62 +
  27/27 verdes contra MySQL real / sem banco, respectivamente.
- `MCP_ADR_INDEX.md` — índice atualizado com a entrada do ADR-018.
- `privates-libs/platform-database-lib/src/platform_database/unit_of_work.py` — fix de
  RETURNING no MySQL dentro de transação (repo separado, já mergeado em `develop`).

## Cadastro real: platform-service-template como exemplo/teste (2026-07-22)

Rodado o pipeline `import_hub` + `import_traceability_matrix` do guardian contra o
repositório REAL `C:\Users\caiog\Documents\repositorios\platform-service-template`
(93 arquivos em `docs/`), não fixtures sintéticas — a primeira validação ponta-a-ponta
contra dado real do mundo. Achou e corrigiu 2 bugs (commit `0ee2d63`, branch
`fix/guardian-real-import-bugs` → merge `6b6a6a1` em `develop`):

1. **`GovDirectiveVersionRow.status` com `max_length=24` insuficiente** — o valor
   `bloqueado-dependencia-externa` (vocabulário LCR, 29 chars) estourava a coluna e
   disparava `ValidationError` do Pydantic antes de chegar no banco. Corrigido para
   `max_length=32` (confirmado: nenhum outro valor de vocabulário passa de 24 chars).
2. **`_import_hub` abortava o lote inteiro num único erro de persistência** — a
   list comprehension deixava um `GuardianValidationError` de UM arquivo escapar até
   o `except` genérico do `dispatch()`, que substituía a resposta inteira por um
   envelope de erro, perdendo o resultado de TODOS os arquivos já importados com
   sucesso no mesmo lote. Corrigido: erros de persistência agora são coletados por
   arquivo em `persist_errors` (mesmo padrão de `parse_errors`), sem abortar o lote.
   2 testes de regressão novos; **65/65 testes verdes** (62 + 2 novos + 1 de status
   longo) + 13/13 aggregator sem regressão.

**Resultado final da importação real** (após os fixes, idempotente/reprodutível):

- 84 diretivas criadas (principles, ADR, standards, reference-architecture,
  runbooks, IT, decisions, LCR, handoffs, specs).
- 80 relações de rastreabilidade importadas da matriz central
  (`documentation-model.md`).
- 2 `persist_errors` genuínos — **drift real de conteúdo no próprio template**, não
  bug do importador: `LCR-005-log-uploader-credential-normalization.md` usa
  `status: "APPROVED"` (inglês/maiúsculo, fora do vocabulário PT-BR) e
  `specs/connector-version-icon.md` usa `status: aprovado`, que só é válido para
  `kind='lib_change_request'`, não para `spec`.
- 7 `parse_errors` (arquivos fora da convenção de nome/front-matter esperada pelo
  importador — não investigado a fundo, fora do escopo deste cadastro).
- `validate_hub` pós-import confirma consistência: os únicos 2 itens fora de sync
  são exatamente os 2 que falharam a persistência; 0 diretivas órfãs.

**Banco persistente (deliberadamente NÃO descartado ao final da sessão, ao contrário
de todo container de teste usado neste projeto):**

- Container Docker: `guardian-example-mysql`, porta `33062`.
- Tenant/database: `devteam_guardian_example`.
- Credenciais: apenas no script local
  `register_template_example.py` (scratchpad da sessão, **não commitado**) — senha
  root `ExampleOnly_2026!`. Para reconectar/reconsultar depois, subir uma
  `TenantSession` apontando pro tenant acima na mesma porta, ou usar
  `docker exec -it guardian-example-mysql mysql -uroot -p`.
- Este container fica de pé como registro consultável (exemplo real de diretriz
  de governança cadastrada), diferente do padrão de container descartável usado em
  todo o resto da sessão — é preciso derrubá-lo manualmente
  (`docker rm -f guardian-example-mysql`) quando não for mais necessário.
