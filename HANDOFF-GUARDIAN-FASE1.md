# Handoff — ADR-018 Guardian, Fase 1 (concluída, mergeada e VALIDADA contra MySQL real)

**Data:** 2026-07-22
**Branch mergeada:** `feat/guardian-domain` → `develop` (local + remoto), branch deletada
**Commits:** `6d238e7` (fix deploy) + `bc8ac46` (feat guardian) + merge `8eff2bb` +
`5510b6c` (doc handoff) + fix pós-validação (3 bugs achados rodando contra MySQL real,
ver seção de validação abaixo).

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

## O que fica para depois (fora do escopo desta Fase 1)

- **Fase 1b** (explicitamente adiada): importador markdown→DB (migração determinística
  do hub de docs do `platform-service-template` para as tabelas `gov_*`) +
  `guardian_validate_hub` com paridade contra `scripts/validate_hub.py` do template
  (critério de aceite: zero divergência).
- **Fases 2-4**: corpo tipado por seção (child tables em vez de `body_context`/
  `body_decision` como TEXT livre), relações/matriz de rastreabilidade como edges,
  escopo `project`/`archetype` completo (hoje `archetype` só existe no rank, colapsado
  em `platform` por decisão do usuário), gates/waivers/conformance profiles (os YAMLs
  estruturados do template: `service-profile`, `service-conformance`,
  `authorization-policy`, `network-policy`).

## Arquivos-chave para retomar

- `ADR-018-DEVTEAM-GUARDIAN.md` — decisões D18.1-D18.10.
- `devteam-mcp-server/src/domains/guardian/` — implementação completa da Fase 1,
  validada contra MySQL real.
- `devteam-mcp-server/tests/test_guardian.py` — 12/12 verdes contra MySQL real.
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
