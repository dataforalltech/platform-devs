# Handoff — ADR-018 Guardian, Fase 1 (concluída e mergeada)

**Data:** 2026-07-22
**Branch mergeada:** `feat/guardian-domain` → `develop` (local + remoto), branch deletada
**Commits:** `6d238e7` (fix deploy) + `bc8ac46` (feat guardian) + merge `8eff2bb`

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
   - `tests/test_guardian.py` — 13 testes de integração (mesmo harness de
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

## Validação feita nesta sessão

- ✅ `ruff check` limpo (guardian + fix do deploy).
- ✅ `black --check` limpo.
- ✅ `mypy` limpo (7 arquivos do domínio guardian, 0 issues).
- ✅ Import sanity: `plugin.register()` do guardian retorna 9 schemas corretos
  (capability `devteam-mcp.guardian_<op>`, required_scope `guardian:<res>:<ação>`,
  data_domain `governance`); auto-discovery confirma `guardian` e `deploy` presentes
  em `src.domains.DOMAINS` (21 domínios totais).

## ⚠️ Pendência importante: testes NÃO executados contra MySQL real

O Docker Desktop não estava rodando no ambiente desta sessão e não subiu a tempo (a
tentativa de start ficou travada na inicialização do WSL/engine por >5min). Os 13
testes de `tests/test_guardian.py` foram escritos espelhando fielmente o harness
provado de `test_session_journey.py`, mas **não foram executados contra um banco
real**. Antes de considerar a Fase 1 encerrada, rodar:

```bash
cd devteam-mcp-server
MYSQL_ROOT_PASSWORD=<senha> python -m pytest tests/test_guardian.py -v -o addopts="" -p no:cacheprovider
```

(a senha funcional local é o `DB_PASSWORD` do container `dtr-e2e-gov` — ver memória
`dataforall-hardening-policy`/sessões anteriores; recuperar via
`docker inspect dtr-e2e-gov --format '{{range .Config.Env}}{{println .}}{{end}}'`
depois de subir o Docker Desktop).

Também vale rodar `tests/test_aggregator.py` completo para garantir que o novo
domínio não introduziu colisão de tool-name com nenhum dos outros 20.

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
- `devteam-mcp-server/src/domains/guardian/` — implementação completa da Fase 1.
- `devteam-mcp-server/tests/test_guardian.py` — testes prontos, aguardando execução real.
- `MCP_ADR_INDEX.md` — índice atualizado com a entrada do ADR-018.
