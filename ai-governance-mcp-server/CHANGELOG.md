# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versionamento: SemVer.

## [Unreleased]

### Changed

- **Release workflow agora é build-only (no push)**: `.github/workflows/ai-governance-mcp-release.yml` gera `linux/amd64` + smoke test pós-build (docker load + python entry validation) + comprime com `gzip -9` + publica como GitHub Actions artifact (`.tar.gz`, retenção 90d). **Não empurra mais para o ACR**. Operador puxa o artifact via `gh run download` e empurra localmente para `d4all.azurecr.io`.
  - Motivação: na release inicial v0.1.0, credenciais válidas localmente foram rejeitadas pelo runner GitHub-hosted (sintoma típico de Network ACL no ACR ou SP com escopo restrito). Modelo "CI builda, humano empurra" elimina a dependência de credenciais ACR no GitHub e funciona com qualquer política de rede.
  - Workflow adiciona Step Summary com instruções copy-paste de `gh run download` + `docker load` + `docker tag` + `docker push`.
  - OPERATIONS.md §6.2 reescrita refletindo o fluxo manual de push.
  - ADR-0005 ganha seção "Modelo de release (revisão pós-incidente)" explicando trade-off + condições para evolução futura (self-hosted runner ou OIDC federation).
  - Secrets `ACR_USERNAME` / `ACR_PASSWORD` provisionados durante debug foram removidos do repo — workflow novo não os referencia.

### Added

- **Docker distribution** (canal recomendado de instalação):
  - Multi-stage `Dockerfile` (builder + runtime python:3.12-slim, ~150 MB final): instala deps com upper bounds pinados, cria usuário não-root `mcp` (UID 10001), embute knowledge-base + ecosystem.yaml na imagem (política versionada com a release), tini como PID 1 para sinal handling.
  - `.dockerignore`: blocklist de caches/build/git/tests/scripts/docs (mantém só `src/` + `pyproject.toml` + `knowledge-base/*.md` + `ecosystem.yaml`).
  - `docker-compose.yml` para exercise local sem configurar client.
  - `.github/workflows/ai-governance-mcp-release.yml`: trigger em tag `ai-governance-mcp/v*` (ou workflow_dispatch). Constrói multi-arch (amd64+arm64) com Buildx, publica em `d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server` (ACR, linux/amd64) com tags `:X.Y.Z`, `:X.Y` e `:latest` (somente releases estáveis), inclui SBOM e provenance, smoke-test pós-publish que pulla a imagem e valida o load do grafo.
  - OPERATIONS.md §6.2 reescrita: pull manual, autenticação ghcr, configuração de client (Claude Desktop + Code), notas sobre cold start (~600-800ms), atualização, build local.
- **`OPERATIONS.md`** — runbook operacional cobrindo install, configuração, operação rotineira (graph updates, drift detection, policies, sugestões), troubleshooting (tools não aparecem, MCP falhou, validator falso positivo, notas Windows), deploy/rollback, métricas, limites conhecidos, contatos.
- **PR validation workflow** (`.github/workflows/pr-validate.yml`) — roda `validate_agent_decision` no diff do PR e posta resultado como comentário via `gh pr comment`. Triggers em `opened/synchronize/reopened` para `main` e `develop`. Por padrão `continue-on-error: true` (informativo, não bloqueia merge) — mude para `false` quando o validator estiver calibrado.
- **`scripts/pr_validate.py`** — variante de `precommit_validate.py` para contexto PR. Aceita `--base` e `--head` (default lê `GITHUB_BASE_REF`/`GITHUB_HEAD_REF`), formata comentário markdown com emoji indicador (🛑/⚠️/✅), suporta `--post-comment` via gh CLI ou `--output-comment <file>`.
- **ADRs** em `docs/decisions/`:
  - `adr-0001-mcp-stack-choice.md` — Python + SDK oficial mcp + stdio.
  - `adr-0002-ecosystem-graph-networkx.md` — grafo in-memory networkx + YAML seed.
  - `adr-0003-suggestion-store-file-per-json.md` — file-per-suggestion JSON.
  - `adr-0004-validator-regex-vs-llm.md` — heurística regex agora, plano híbrido para depois.
- **`CHANGELOG.md`** seguindo Keep a Changelog.
- 14 testes em `tests/test_pr_validate.py`: matriz de renderização do comentário (critical→BLOCKED, high→HIGH RISK, medium, low→OK; omissão de seções vazias), `_post_comment` (sem PR_NUMBER, extração de `GITHUB_REF`, gh CLI ausente), helpers de diff (truncamento, parsing de files, agregação de commits).

### Changed

- **Dependências pinadas com upper bound major** em `pyproject.toml`: `mcp>=1.2.0,<2.0`, `pydantic>=2.6.0,<3.0`, `pydantic-settings>=2.2.0,<3.0`, `networkx>=3.2,<4.0`, `pyyaml>=6.0,<7.0`. Reduz risco de breaking change silenciosa em bump automático. Versões instaladas durante validação 0.1.0: mcp=1.27.0, pydantic=2.12.5, pydantic-settings=2.13.1, networkx=3.6.1, pyyaml=6.0.3.

### Fixed

- **`_DEPENDENCY_PATTERNS` regex false positive (ADR-0004 follow-up)**: 4º padrão era literal alternação `requirements\.txt|package\.json|pyproject\.toml`, disparava em qualquer texto contendo o nome do manifesto (docstrings, strings literais). Agora exige verbo de modificação (PT/EN: adicionei, incluir, colocar, put, add, new, requires, pin, upgrade, bump) dentro de janela de 60 chars antes da menção. Cobertura: 2 regression tests em `tests/test_decision_validator.py`.

- **`_NOOP_DOWNGRADE_RE` regex em `migration_tool.py`**: agora aceita assinaturas anotadas `def downgrade() -> None:` além de `def downgrade():` simples.

### Test coverage

- `tests/test_ownership.py` — 30 casos para as 5 tools (get_service_ownership/get_service_dependencies/get_port_map/check_scope/validate_lib_change). Inclui resolução canônica/alias/short-name, deprecation redirect, risk thresholds, HARD STOP §18, GraphUnavailable propagation.
- `tests/test_migration.py` — 17 casos cobrindo cada um dos 5 §29 checks (sem ORM, sa.text wrapper, idempotency IF NOT EXISTS, no destructive ops em upgrade, downgrade obrigatório).
- `tests/test_adr.py` — 12 casos para create_adr (numeração sequencial, frontmatter, parametric validation, skip de não-numeric files, tmp_path isolado).

Total: **232 tests passing** (171 + 61 novos).

## [0.1.0] - 2026-05-05

### Added

#### MCP Server base
- 13 tools MCP via stdio: 9 de governança textual + 4 de grafo do ecossistema.
- Knowledge base com 13 markdown files (política universal + 8 camadas + 4 tópicos).
- `EcosystemGraph` in-memory baseado em `networkx.MultiDiGraph`, seedado por `knowledge-base/ecosystem.yaml`.
- 73 nós (1 team, 4 libs, 22 ports, 26 services, 20 contracts) e 166 arestas alinhados com AGENTS.md §47/§49.
- 80 testes pytest cobrindo cada regra do validador, regras canônicas e indisponibilidade do grafo.
- CI dedicado em `.github/workflows/ai-governance-mcp-ci.yml` (pytest + ruff + smoke + structural validation).
- Logs estruturados JSON via stderr (stdout reservado ao protocolo MCP).
- Settings tipado via `pydantic-settings` com prefixo `GOVERNANCE_`.
- Smoke test via cliente MCP stdio em `scripts/smoke_test.py` com modo `--watch` (heartbeat).

#### Drift scanner
- `scripts/scan_ecosystem.py` — CLI read-only que compara `ecosystem.yaml` com repos no disco (pyproject.toml, .env*, docker-compose.yml). Detecta conflitos (porta), missing_from_yaml (repo descoberto não modelado), missing_on_disk (yaml com repo não encontrado, distinguindo deprecated [esperado] de active [warning]), lib_drift, consume_drift.
- Auto-detect inteligente do `--path` (sobe na árvore pulando worktrees/.claude).
- Resolução de aliases (pyproject name + basename) contra ids e `aliases` field.
- Output text ou JSON. Exit 1 em conflitos, 0 em warnings, 2 em input inválido.
- 21 testes em `tests/test_scanner.py` com fixtures programáticas.

#### Cross-repo suggestion channel
- 4 tools MCP novas:
  - `submit_suggestion` (validação rigorosa de category/severity, resolução automática alias/deprecated_by para canônico, `target_repo_canonical` preservado para auditoria).
  - `list_suggestions` (filtros target_repo alias-aware, status, category, severity, source_agent, limit).
  - `get_suggestion` (payload completo pelo id).
  - `update_suggestion_status` (histórico append-only com `ts/note/by`, idempotente em no-change).
- Persistência: 1 arquivo JSON por sugestão em `<kb>/suggestions/<id>.json`. ID `YYYYMMDDTHHMMSSffffff-XXXXXXXX` (sortable). Atomic write via tmp + replace.
- Settings: `GOVERNANCE_SUGGESTIONS_PATH` opcional.
- 30 testes em `tests/test_suggestions.py`.

#### Pre-commit hook
- `scripts/precommit_validate.py` — git hook que invoca `validate_agent_decision` via stdio MCP no diff staged. Bloqueia commit em `risk=critical`, avisa em `high`/`medium` (configurável via `PRECOMMIT_BLOCK_ON_HIGH`).
- Skip em merge/rebase/amend, fail-safe em problema de transporte (nunca quebra commit por infra), truncamento de diff em 8000 chars, skip em PR >50 arquivos.
- Heurística de detecção conservadora (apenas `adds_dependency` por path-match; outros flags ficam False — o validator detecta via regex no `proposed_change`).
- Mapeamento de paths para layers (backend, database, frontend, infrastructure, testing, security, observability, integrations).
- 26 testes em `tests/test_precommit_hook.py`.

### Fixed

- **Validator: falso positivo em negações.** A regex `_DELETE_TEST_PATTERNS` casava `removi\s+teste` mesmo quando precedido de "Não". Adicionada `_is_negated()` com janela contextual de 40 chars sem cruzar fim de sentença, cobrindo PT/EN (não, sem, nunca, jamais, no, not, don't, didn't, doesn't). Inclui regression test que garante que `"removi teste"` sem negação ainda bloqueia.
- **Validator: agregação de via= em consumers.** Quando o mesmo consumidor consome múltiplos contratos do mesmo provider, antes só aparecia 1 via path. Agora todos os contratos consumidos são agregados em `via=[{relation, target}, ...]`.

### Changed

- **Ecosystem graph alinhado com canônicos**:
  - `platform-cdc` corrigido de porta 8018 para **8017** (memória do projeto estava errada; AGENTS.md §47 e DEVOPS_STANDARDS.md §3 confirmam).
  - `rag-service` → `dataforall-rag-service` (alias preservado para nome legacy).
  - `agents-factory` → `dataforall-agents-factory` (idem).
  - `port-8018` agora aponta para `platform-api-gateway` (era CDC erradamente).
- **Ecosystem graph expandido**: de 24 nós / 50 arestas → 73 nós / 166 arestas. Modela todos os 22 serviços canônicos da AGENTS.md §47, com portas, descrições, `explicit_non_responsibilities`, contratos provisos, eventos produzidos, libs usadas, e dependências cross-service da §49.
