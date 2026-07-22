# Handoff — ADR-018 Guardian, Fase 1 + 1b + 1c (concluídas, mergeadas, VALIDADAS contra MySQL real)

**Data:** 2026-07-22
**Branches mergeadas em `platform-devs`:** `feat/guardian-domain`,
`feat/guardian-hub-importer`, `feat/guardian-lcr-schema` → `develop` (local + remoto,
todas deletadas).
**Branch mergeada em `privates-libs/platform-database-lib`:**
`fix/unit-of-work-mysql-returning-v2` → `develop` (repo separado, ver seção própria).
**Commits (platform-devs):** `6d238e7` (fix deploy) → `bc8ac46` (feat guardian Fase 1) →
merge `8eff2bb` → docs `5510b6c`/`29558b0` → `6f0271b` (Fase 1b importador) → merge
`b7a8dd8` → docs `45781b9` → `603415e` (Fase 1c LCR/handoffs/specs) → merge `c6a1ba2`.

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

## O que fica para depois (fora do escopo de Fase 1 + 1b + 1c)

- **Fase 2**: corpo tipado por seção (child tables em vez de `body_context`/
  `body_decision` como TEXT livre), tabela de relações `governado_por`/matriz como
  arestas tipadas, escopo `project`/`archetype` completo (hoje `archetype` só existe no
  rank, colapsado em `platform` por decisão do usuário).
- **Fases 3-4**: gates/waivers/conformance profiles (os YAMLs estruturados do template:
  `service-profile`, `service-conformance`, `authorization-policy`, `network-policy`).

## Arquivos-chave para retomar

- `ADR-018-DEVTEAM-GUARDIAN.md` — decisões D18.1-D18.10.
- `devteam-mcp-server/src/domains/guardian/` — Fase 1 + 1b + 1c completas, validadas
  contra MySQL real (`db/store.py`, `catalog.py`, `importer.py`, `models.py`).
- `devteam-mcp-server/tests/test_guardian.py` + `test_guardian_importer.py` — 37/37 +
  16/16 verdes contra MySQL real / sem banco, respectivamente.
- `MCP_ADR_INDEX.md` — índice atualizado com a entrada do ADR-018.
- `privates-libs/platform-database-lib/src/platform_database/unit_of_work.py` — fix de
  RETURNING no MySQL dentro de transação (repo separado, já mergeado em `develop`).
