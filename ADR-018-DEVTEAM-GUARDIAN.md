# ADR-018 — DevTeam como Guardião das Diretrizes (domínio `guardian`)

**Status:** Accepted (design travado 2026-07-22) · implementação faseada · **Date:** 2026-07-22 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-017 (project-product — ligação repo-template↔projeto via `external_link`), ADR-009 (catálogo capability/operation), ADR-005 (HILT/PEP p/ waivers), ADR-001 (ORM/PostgreSQL, SQLAlchemy proibido)
**Fonte do padrão:** `platform-service-template` (hub de governança documental — 5 camadas + perfis/conformance YAML validados por `scripts/validate_hub.py`)

## Context

O **maior objetivo** do DevTeam é ser o **guardião das diretrizes** — gerenciar, aplicar e garantir processos,
arquitetura, segurança, conexões e qualidade, **global ou por-projeto**. Hoje essas diretrizes vivem no repo
`platform-service-template` como **arquivos markdown + front-matter YAML** (um arquivo por registro) e uma **matriz
de rastreabilidade dentro de um markdown**, com um validador determinístico (`scripts/validate_hub.py`, 1418 linhas)
rodando como gate de CI.

Isso é a **anti-forma** para software: drift (a mesma estrutura descrita em vários lugares), perda (READMEs de índice
mantidos à mão), e não-consultável. O padrão em si é **excelente e já normalizado** — só está encodado como arquivos.
Este ADR decide transformá-lo em **software robusto**: tabelas normalizadas + CRUD versionado + escopo global/projeto,
**sem JSON-blob e sem arquivos soltos**.

**O padrão do hub (a extrair):** modelo de 5 camadas — Princípios (`P-*`, crença) → ADR (`ADR-*`, decisão) →
Engineering Standards (`STD-*`, regras RFC 2119 + **checklist de conformidade**) → Reference Architecture (`ARCH-*`,
descritivo + `file:line`) → Runbooks (`RUNBOOK-*`, operação) + Instruções de Trabalho (`IT-*`) e `decisions/`
(histórico plataforma). Cada registro tem front-matter (`type/camada/status/escopo/ultima_atualizacao/governado_por`)
e ID canônico imutável. Há **matriz de rastreabilidade** (ADR↔Princípio↔Standard↔Reference↔Runbook), exceções
auditáveis, e **dados já estruturados** (YAML schema-validado): `service-profile`, `service-conformance`
(controls: id/status/reason/**evidence**), `authorization-policy`, `network-policy`, `frontend-product-profile`.

## Decision

**D18.1 — Domínio `guardian` no devteam-mcp.** Um novo domínio canônico
`devteam-mcp-server/src/domains/guardian/` (models Pydantic → ORM `platform_database` dual-db mysql/postgres,
tenant-scoped, credencial-zero), seguindo o padrão dos domains existentes (session/config/product-owner).
`ai-governance` (hoje lê markdown do template) passa a **consumir** o guardian (read-through), deixando de carregar
arquivos.

**D18.2 — Rejeição explícita de JSON-blob e arquivos soltos.** (a) front-matter → **colunas**; (b) seções repetíveis
(alternativas de ADR, requisitos MUST/SHOULD, config params, itens de checklist, passos de runbook, `file:line`) →
**tabelas-filhas tipadas** (1:N), nunca lista JSON; (c) matriz de rastreabilidade → **tabela de arestas** tipadas,
nunca célula markdown; (d) índices de camada → **query**, não README. `TEXT` só para prosa genuína (Contexto/Decisão/
Racional). `payload_json` só no evento de conformidade append-only (snapshot de proveniência).

**D18.3 — Identidade imutável + versionamento append-only.** `gov_directive` (uid natural imutável, nunca deletado —
supersedência via novo uid + `superseded_by_uid`) + `gov_directive_version` (revisões append-only, `status`,
`is_current`, `content_sha256`). A vigência tem **um lar só**: a version. Invariante "exatamente uma vigente por uid"
é **app-level** via `store.transaction()` (UPDATE is_current=0 → INSERT is_current=1 → commit) — o MySQL não suporta
índice parcial (`capabilities.supports_partial_index=False`).

**D18.4 — Escopo hierárquico total (3 tiers agora; `archetype` adiado, aditivo).**
`baseline(0) < platform(1) < project(3)` numa coluna PRÓPRIA `directive_scope` + `scope_rank` materializado (a
coluna-padrão `scope` da plataforma fica intocada; **não** se inventa `id_environment`). `resolve_effective(project,
uid)` retorna a revisão vigente da linha de **maior scope_rank aplicável** + `origin_scope`. O tier `archetype(2)`
(família de serviço, ex. gateway-type) fica **reservado** e é adicionado depois sem quebra quando houver demanda real
(evita tier morto — o `scope_rank` já deixa o buraco). Override/desativação por-projeto em `gov_project_override`
(nunca 2ª linha do header).

**D18.5 — Baseline é seed versionado por-tenant, não DB compartilhado.** O DevTeam distribui o catálogo curado como
**seed com proveniência** (`baseline_version` + `content_sha256`) para o DB de cada tenant (precedente
`notification.provision_tenant`/`seed_tenant`) — respeita o modelo `for_tenant` credencial-zero. Consistência
cross-tenant = igualdade **verificável** de fingerprint, não FK. (Control-plane DB central fora de `for_tenant` fica
como ADR futuro **explicitamente adiado**, não implícito.)

**D18.6 — `project_ref` é referência FRACA.** Opaca, validada no write por chamada ao project-product (ADR-017);
**nunca FK** (é cross-service/cross-DB). Órfãos → `guardian_sweep_orphans`. O repo-template é um **Product**; cada
serviço derivado é um **Project** com `RepositoryBinding.external_link` apontando o repo SCM.

**D18.7 — Constraints são costuradas (não saem de graça do ORM).** `create_table_from_model` só emite colunas
(`ddl.py:433`). Todo CHECK/UNIQUE/FK via `model_copy(update={checks,uniques,foreign_keys})` e todo índice (incl.
reintroduzir `ix_excluded` e indexar colunas de FK/arestas) via `CreateIndex` explícito.

**D18.8 — Requisito com identidade em dois níveis.** `requirement_uid` (código estável, ex. `SEC-022`) persiste
através de versões; a linha é por `(directive_uid, version)`. FK composta `(directive_uid, version, req_code)` só para
links **intra-versão** (checklist→requisito da mesma revisão); links cross-versão (conformance/waiver/check)
referenciam `req_code`+`directive_uid` como **referência soft** com política "segue a versão adotada"
(`assessed_version`).

**D18.9 — Guardião é registro + política, NÃO executor.** A autoridade de execução de gate é
pipeline/qa/pre-commit/boot. O guardian **ingere** resultados (`record_check_result`), aplica política, gerencia
waiver (`gov_waiver` com `non_waivable` bloqueando waiver de invariantes inegociáveis; `approver_ref` + HITL
platform-governance) e **materializa** a visão de conformidade (`check_compliance`). `apply_standard(project, std)`
semeia adoção + `gov_conformance_control` `not_assessed` por requisito.

**D18.10 — Migração determinística markdown→DB.** Importador idempotente (chave `directive_uid`) reusando o parser
do `validate_hub.py` (`read_front_matter`/`_extract_ids`/`_matrix_adr_numbers`). **Critério de aceite:
`guardian_validate_hub` vs. `validate_hub.py` no mesmo commit = zero divergência.** Depois o hub markdown vira
read-only e o **banco é a fonte-da-verdade**.

## Modelo de dados (normalizado — resumo; detalhe na Reference/implementação)

Todas tenant-scoped, colunas-padrão da plataforma injetadas (`id`/`id_user_*`/`create_on`/`active`/`excluded`/`scope`),
soft-delete (`excluded=0`) exceto onde "append-only".

- **`gov_directive`** — `directive_uid` UNIQUE, `kind` (FK→gov_kind_capability), `directive_scope`+`scope_rank`,
  `project_ref` NULL (fraco, CHECK `(scope='project')=(project_ref IS NOT NULL)`), `title`, `superseded_by_uid` NULL,
  `owner_ref` NULL.
- **`gov_kind_capability`** — `kind` PK, `layer` NULL, `allows_rfc2119`, `allows_fileline`, `body_shape`
  (prose/typed/mixed).
- **`gov_directive_version`** — FK `directive_uid`, UNIQUE`(directive_uid,version)`, `status` (FK→gov_status_vocab),
  `is_current`, `body_context`/`body_decision` TEXT NULL, `change_reason`, `author_ref`, `content_sha256`.
- **Vocabulários** (seed por-tenant): `gov_status_vocab`, `gov_rfc2119_level`, `gov_conformance_state`.
- **Filhas tipadas** (FK composta `(directive_uid,version)`): `gov_requirement` (+UNIQUE`(directive_uid,version,req_code)`),
  `gov_std_config_param`, `gov_std_checklist_item`, `gov_adr_alternative`, `gov_adr_consequence`, `gov_runbook_step`,
  `gov_runbook_symptom`, `gov_lcr_detail`/`gov_lcr_affected_service`, `gov_principle_implication`, `gov_refarch_fileref`
  (file:line tipado), `gov_handoff_participant`/`gov_handoff_item`, `gov_wi_step`.
- **Relações:** `gov_relation`(from_uid, rel_type, to_uid) direção canônica (`depends_on/derived_from/traced_to/
  implements/operates/cites/governed_by/complements`); `gov_matrix_exception`; `gov_cross_cutting_governance` (wildcards
  `STD-*`).
- **Projeto/adoção/conformidade:** `gov_project_override`, `gov_adoption`, `gov_conformance_control` (soft-ref ao
  requisito, CHECK de presença de evidence/reason), `gov_conformance_event` (**append-only**).
- **Gates:** `gov_check` (catálogo, `enforcement_type`), `gov_gate_result` (**ingestão**), `gov_waiver`
  (`non_waivable`).

## Faseamento (aditivo — cada fase = migração DDL-IR nova + lote de tools)

1. **Núcleo versionado** — `gov_directive`/`version`/`kind_capability`/`status_vocab`; CRUD directive; importador dos
   kinds `platform`; `validate_hub` (front_matter/status/type_layer). Inclui já o wiring de constraints (D18.7) e o
   `transaction()` de `is_current` (D18.3).
2. **Corpo tipado + relações** — filhas por kind (incl. refarch_fileref/handoff/wi) + `gov_relation` + rastreabilidade.
3. **Escopo projeto + adoção** — `directive_scope`/`resolve_effective` + `gov_project_override` + seed baseline
   por-tenant + ligação project-product/`external_link` + `adopt`/`apply_standard`. **O diferencial do produto.**
4. **Guardião ativo** — `gov_check`/`gate_result`/`conformance`/`waiver` + reconciliação pipeline/qa + HITL nos waivers.

## Consequences

**Positivas:** as diretrizes viram dados consultáveis/versionados/escopáveis; o DevTeam pode aplicar e garantir
conformidade por-projeto; a matriz de rastreabilidade e os índices deixam de degradar (query, não arquivo mantido à
mão); a paridade com `validate_hub.py` prova a migração sem perda.

**Negativas/riscos:** um domínio grande (muitas tabelas) — mitigado pelo faseamento; `resolve_effective` é orquestração
multi-read (desvio documentado do padrão persona single-table) — medir antes de otimizar; `project_ref` fraco exige
`sweep_orphans`; o importador precisa de paridade exata com `validate_hub.py` (critério de aceite duro).

## Open questions

1. Baseline seed-per-tenant (adotado) vs control-plane DB central — abrir ADR separado só se auditoria cross-tenant
   virar requisito duro. **Adiado explicitamente.**
2. `archetype` tier — reservado no `scope_rank`; ativar quando houver regra real por-família de serviço.
3. `adoption_contract_template`: cláusulas typed (`gov_contract_clause`) na Fase 4 ou prosa até o gate consumir DoR/DoD.
