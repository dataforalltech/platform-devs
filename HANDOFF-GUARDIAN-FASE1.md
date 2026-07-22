# Handoff — ADR-018 Guardian, Fase 1 + Fase 1b (concluídas, mergeadas e VALIDADAS contra MySQL real)

**Data:** 2026-07-22
**Branches mergeadas:** `feat/guardian-domain` e `feat/guardian-hub-importer` → `develop`
(local + remoto, ambas deletadas)
**Commits:** `6d238e7` (fix deploy) → `bc8ac46` (feat guardian Fase 1) → merge `8eff2bb` →
`5510b6c`/`29558b0` (docs handoff) → `6f0271b` (feat Fase 1b importador) → merge `b7a8dd8`.

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

**Deliberadamente FORA de escopo** (documentado em `importer.py` e para retomar depois):
- `lib-change-requests/`, `handoffs/`, `specs/` — front-matter heterogêneo e vocabulário
  de status próprio (LCR tem `pendente-aprovacao/aprovado/implementado/...`, diferente
  do `STATUS_VOCAB` normativo); exigiria EAV ou colunas específicas por kind — **Fase 1c**.
- Relações `governado_por` e a matriz de rastreabilidade N:N:N:N de
  `documentation-model.md` — exige uma tabela de arestas tipadas
  (`gov_directive_reference(from_uid, to_uid, relation_type)`), fora do núcleo
  versionado da Fase 1 — **Fase 2**.
- Paridade completa com `scripts/validate_hub.py` (templates YAML/K8s/Istio, Statement
  of Applicability, "semantic currentness", segurança de `.mcp.json`) — esse script
  cobre superfícies de infra/segurança que não são responsabilidade do guardian
  ("registry+policy, NÃO executor" — D18); `guardian_validate_hub` cobre só drift de
  governança documental (filesystem × `gov_directive`/`gov_directive_version`).

## O que fica para depois (fora do escopo de Fase 1 + Fase 1b)

- **Fase 1c**: schema para LCR/handoffs/specs (campos de gestão de mudança, vocabulário
  de status próprio por família).
- **Fase 2**: corpo tipado por seção (child tables em vez de `body_context`/
  `body_decision` como TEXT livre), tabela de relações `governado_por`/matriz como
  arestas tipadas, escopo `project`/`archetype` completo (hoje `archetype` só existe no
  rank, colapsado em `platform` por decisão do usuário).
- **Fases 3-4**: gates/waivers/conformance profiles (os YAMLs estruturados do template:
  `service-profile`, `service-conformance`, `authorization-policy`, `network-policy`).

## Arquivos-chave para retomar

- `ADR-018-DEVTEAM-GUARDIAN.md` — decisões D18.1-D18.10.
- `devteam-mcp-server/src/domains/guardian/` — Fase 1 + Fase 1b completas, validadas
  contra MySQL real (`db/store.py`, `catalog.py`, `importer.py`).
- `devteam-mcp-server/tests/test_guardian.py` + `test_guardian_importer.py` — 26/26
  verdes contra MySQL real.
- `MCP_ADR_INDEX.md` — índice atualizado com a entrada do ADR-018.

## Achado colateral para investigar depois (fora do escopo desta sessão)

`UnitOfWork.fetch_one` (`privates-libs/platform-database-lib/src/platform_database/unit_of_work.py`)
não emula `RETURNING` no MySQL como o `MySQLPool` top-level faz (ver `repository.py`
`_fetch_returning_row`, comentário "MySQL's pool emulates RETURNING on fetch_one").
Qualquer domínio que chame `Repository.insert()`/`upsert()` com `returning` não-None
**dentro de um `transaction()`** vai quebrar com `ProgrammingError` no MySQL. Hoje o
guardian contorna passando `returning=None` onde não precisa do id, mas isso é um
gap real da lib compartilhada — vale corrigir na origem (fazer `UnitOfWork.fetch_one`
emular RETURNING como o pool normal) para não pegar o próximo domínio de surpresa.
