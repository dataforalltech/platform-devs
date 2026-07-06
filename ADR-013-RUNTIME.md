# ADR-013 — Runtime

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-012 (emite eventos), ADR-009 (lê catálogo / `contract.execution.idempotent`), ADR-005 (HILT/PDP) e ADR-007 (risk tiers), ADR-004 (capability token)

## Context

O `platform-dev-agent` já executa o Modo B autônomo: **plan → approve → execute** derivado de um
runbook versionado (DAG), com aprovação humana N1/N2, orçamento por run, enforcement de capability e
resume-safety guardado. Isso **não é especulação** — está codificado e testado (`AutonomousPipeline`,
`PlanBuilder`, `ApprovalGate`, `PlanExecutor`, `PlanRepository`, `RunBudget`, `CapabilityResolver/Enforcer`,
`RunbookSelector`). O que falta é **formalizar como arquitetura** o que existe, nomear as garantias que o
runtime oferece, e **marcar os GAPs** (Scheduler, Memory, motor de Risk/Policy formal) para que as próximas
fases saibam onde encaixar.

Esta ADR **descreve o runtime**; ela **não** redefine:

- **a taxonomia de eventos** (ADR-012) — o runtime *emite* eventos nos pontos de transição; aqui só
  referenciamos quais;
- **o capability/risk model** (ADR-007/009) — o runtime *consome* `authz.capability`, `risk.*` e
  `contract.execution` do catálogo; aqui só descrevemos como a execução reage a eles.

Fundação real relevante (aterramento, não invenção):

| Componente | Estado | Onde vive (`platform-dev-agent`) |
|---|---|---|
| **Planner** | EXISTE | `plan/builder.py` (`PlanBuilder`) + `runbook/dag.py` (topo-sort Kahn) |
| **Approver** | EXISTE | `plan/approval.py` (`ApprovalGate` N1/N2) |
| **Executor** | EXISTE | `plan/executor.py` (`PlanExecutor`, transições guardadas) |
| **Budget** | EXISTE | `budget.py` (`RunBudget`, 3 eixos) |
| **Recovery/Resume** | EXISTE | `plan/repository.py::reconcile_orphans` + guardas do executor |
| **Retry** | PARCIAL | só READ (`config.py::tool_max_retries`, `GatewayToolClient`); WRITE nunca |
| **Persistência guardada** | EXISTE | `PlanRepository` (in-memory) + `repository_pg.py` (Postgres) |
| **Orquestração** | EXISTE | `pipeline.py` (`AutonomousPipeline`) |
| **Scheduler** | **GAP** | — (definido como alvo nesta ADR) |
| **Memory** | **GAP** | — (definido como alvo nesta ADR) |
| **Risk/Policy engine formal separado** | **GAP** | risco hoje é *derivado* no `CapabilityResolver` (ADR-009 quer no catálogo) |

## Decision

**D13.1 — O Runtime é o executor de planos do Control Plane, não um LLM livre.** O runtime transforma um
*intent* num **Plan** derivado de um **runbook versionado** e o executa passo a passo pelo gateway. O plano
**nunca** nasce de um LLM solto (evita o fallback "genérico" silencioso do agente de marketing): nasce do
DAG do runbook, ordenado topologicamente e validado (`PlanBuilder.build_from_runbook`). Um LLM só entra como
*fallback* de **seleção de runbook** (`RunbookSelector`), sempre restrito a um **enum fechado** de ids do
catálogo — nunca inventa um runbook inexistente.

**D13.2 — Componentes do Runtime (pipeline canônico).**

```
intent ─▶ [RunbookSelector] ─▶ [Planner: PlanBuilder + DAG] ─▶ repo.create(PENDING)
                                                                     │
                                          PlanProposal (poll N1 [+ poll N2 high-risk])
                                                                     │  (aguarda humano — ADR-005 HILT)
                                          resposta ─▶ [Approver: ApprovalGate] ─▶ ApprovalDecision
                                                                     │
                            [Budget: RunBudget.start] ─▶ [Executor: PlanExecutor] ─▶ [ItemResult...]
                                                                     │
                                                    repo.transition_plan(final)
```

| Componente | Papel | Estado |
|---|---|---|
| **Planner** (`PlanBuilder`) | runbook → DAG topo-sort (Kahn, rejeita ciclo/órfão) → resolve `capability`+`risk` por item → valida `input_schema` (fail-early) → propaga `required` → carimba `runbook_version`. | EXISTE |
| **Approver** (`ApprovalGate`) | resposta bruta do poll → `ApprovalDecision`. N1 = seleção do plano (labels / `__approve_all__` / verbal fechado); N2 = confirmação **individual** de item HIGH via `__confirm_high__`. Verbal/"aprovar tudo" **nunca** cobre high-risk. | EXISTE |
| **Executor** (`PlanExecutor`) | itera itens em ordem topológica (`sequence_num`), claim guardado, chama a tool **via gateway**, persiste resultado, deriva status final por `required`. | EXISTE |
| **Budget** (`RunBudget`) | teto por run em 3 eixos simultâneos (tokens, wall-clock, tool-calls). Charge+check **antes** do dispatch. | EXISTE |
| **Recovery/Resume** (`reconcile_orphans` + guardas) | retoma um plano sem duplicar side-effects; reconcilia órfãos EXECUTING. | EXISTE |
| **Retry** (`GatewayToolClient` + `Settings`) | backoff exponencial — **só READ**. WRITE nunca retenta (ver D13.7). | PARCIAL |
| **Scheduler** | disparo de runs no tempo (cron/atraso/gatilho de evento). | **GAP** — alvo em D13.8 |
| **Memory** | contexto durável entre runs/sessões (fatos, artefatos, decisões). | **GAP** — alvo em D13.9 |

**D13.3 — Máquina de estados do Plano.** Estados de `PlanStatus` (`models/plan.py`):

```
                 rejeitado (N1)
        ┌──────────────────────────────▶ REJECTED  (terminal)
        │
     PENDING ──approve──▶ APPROVED ──claim guardado──▶ EXECUTING ──┬─▶ DONE     (todos os itens DONE)
   (aguarda                (ainda não                              ├─▶ PARTIAL  (done<total, sem falha bloqueante)
    aprovação)              começou)                               └─▶ FAILED   (item `required` não-DONE)
        │
        └──TTL de aprovação sem resposta──▶ EXPIRED  (terminal; ver D13.8 open q.)
```

- A transição de entrada é **guardada**: `EXECUTING` só é alcançado a partir de `PENDING|APPROVED`
  (`transition_plan(expected=(PENDING, APPROVED), new=EXECUTING)`). Se outro worker já moveu o plano, o
  executor **resume** do estado persistido em vez de reexecutar.
- `EXPIRED` é o alvo do TTL de aprovação (o campo existe; o disparo por tempo depende do Scheduler — D13.8).

**D13.4 — Máquina de estados do Item.** Estados de `ItemStatus`:

```
   PENDING ─┐
   READY  ──┤ (claimable) ──claim guardado──▶ EXECUTING ──┬─▶ DONE
   APPROVED ┘                                             └─▶ ERROR
        │
        ├─ dependência não-DONE ───────────▶ SKIPPED  ("dependency did not complete")
        ├─ N1 não aprovou ─────────────────▶ SKIPPED  ("not approved (N1)")
        ├─ HIGH sem N2 ────────────────────▶ SKIPPED  ("high-risk not approved / unanswered (N2)")
        ├─ orçamento estourado ────────────▶ SKIPPED  ("budget exceeded")
        │
   EXECUTING ──órfão além do TTL, se WRITE──▶ NEEDS_RECONFIRM  (nunca reexecuta cego — D13.7)
   EXECUTING ──órfão além do TTL, se READ───▶ READY            (seguro re-claim)
```

Estados terminais do item: `DONE | ERROR | SKIPPED`. Um item terminal **nunca** é reexecutado num resume.
`NEEDS_RECONFIRM` é *não-claimable* (a guarda `expected=(PENDING, READY, APPROVED)` não casa), então o
resume o pula — resume-safe por construção.

**D13.5 — Garantias de execução (o contrato que o Runtime oferece).**

| # | Garantia | Como é obtida |
|---|---|---|
| G1 | **Isolamento por item.** Uma falha (inclusive `CapabilityViolation`) vira `ERROR` do item, **nunca** aborta o plano. | `assert_allowed` + a chamada da tool ficam **dentro** do `try` por item; `except Exception` isola. |
| G2 | **Sem dupla execução (anti-TOCTOU).** Dois workers correndo o mesmo item: só um vence o claim `PENDING→EXECUTING`. | `transition_item(expected=…, new=EXECUTING)` guardado; `False` = no-op idempotente. |
| G3 | **Resume-safe.** Um resume nunca refaz um item terminal nem um WRITE órfão. | terminal ⇒ `continue`; WRITE órfão ⇒ `NEEDS_RECONFIRM` (não-claimable); READ órfão ⇒ `READY`. |
| G4 | **Status final honesto.** `required` não-DONE ⇒ `FAILED`; todos DONE ⇒ `DONE`; senão `PARTIAL`. | `_final_status` percorre itens usando o flag `required`. |
| G5 | **Parada limpa por orçamento.** Estourou o teto ⇒ demais itens `SKIPPED` e plano fechado com status coerente. | `BudgetExceeded` é capturado no loop; nunca escapa do gerador. |
| G6 | **Skip encadeado.** Dependência não-DONE "envenena" o dependente (evita rodar com input ausente). | checagem `depends_on ⊆ done_task_ids` antes do claim. |
| G7 | **Redação antes de persistir.** Payload de tool sensível é redigido antes do DB e do `ItemResult`. | `redact(tool, output)` no caminho de sucesso (ADR-005 output policy). |
| G8 | **Ordem determinística.** Execução segue o topo-sort (`sequence_num`); empates lexicográficos. | `sorted(items, key=sequence_num)`; DAG por Kahn com desempate lexicográfico. |

**D13.6 — Aprovação N1/N2 é parte do Runtime, delegando a política a ADR-005.** O Approver **produz** a
decisão; **quem exige** N2 vem do `risk` do item (HIGH ⇒ confirmação individual). A ADR-009 mapeia
`risk.approval_required = none|N1|N2` no catálogo; o runtime **consome** esse nível — não o redefine. Um item
HIGH aprovado em N1 mas **sem** resposta N2 é marcado *unanswered* (distinto de *rejeitado*): o chamador
**re-emite o poll** em vez de descartar silenciosamente o passo (que pode ser o ponto central do run).

**D13.7 — Recovery/Retry ligados a `contract.execution.idempotent` (ADR-009 D9.8).** Aterramento verificado:
o gateway `platform-mcp` **não deduplica writes por `Idempotency-Key`** (só retenta reads). Por isso hoje o
runtime opera com `Settings.resume_writes_safe = False` e a política de retry (`tool_max_retries`, backoff
exponencial) **só cobre READ**. WRITE nunca é retentado nem resumido; um WRITE órfão vira `NEEDS_RECONFIRM`.

**Alvo (fecha o loop com o catálogo):** trocar a heurística global por **decisão por metadata**. Quando o
catálogo (ADR-009) marca `contract.execution.idempotent = true` para uma Operation, o Planner pode marcar o
item como *resume-safe*, e o Executor passa a poder retentar/resumir aquele WRITE. A tabela abaixo é o alvo:

| `idempotent` (catálogo) | READ | WRITE |
|---|---|---|
| `true`  | retry + resume | retry + resume (**alvo** — hoje bloqueado) |
| `false` | retry + resume | **sem** retry, **sem** resume (órfão ⇒ `NEEDS_RECONFIRM`) |

**D13.8 — Scheduler (GAP — alvo).** Hoje um run é disparado sincronamente pelo pipeline. O alvo é um
**Scheduler** que dispara runs por: (a) **cron/agenda**, (b) **atraso/one-shot**, e (c) **gatilho de evento**
(assinando eventos da ADR-012, ex.: `RunbookCompleted` encadeia outro runbook). Responsabilidades: honrar o
**TTL de aprovação** (mover planos parados de `PENDING → EXPIRED`), respeitar concorrência por
sessão/recurso, e **reenfileirar resumes** de planos interrompidos (chamando `reconcile_orphans` antes de
re-claim). O Scheduler **não** reimplementa a máquina de estados; apenas **agenda quando** o Executor roda.

**D13.9 — Memory (GAP — alvo).** Hoje o estado durável é o **próprio plano** (Postgres:
`dev_plans`/`dev_plan_items`/`dev_plan_approvals`) + a redação. Falta uma **Memory** de nível de
sessão/projeto: fatos, artefatos e decisões que sobrevivem entre runs e alimentam o próximo plano (ex.:
"serviço X já deployado na versão Y", "decisão arquitetural Z"). Alvo: uma store consultável, **escopada por
sessão/tenant**, alimentada pelos `ItemResult` e por eventos (ADR-012), lida pelo Planner como contexto.
Fronteira explícita: Memory é **estado do runtime**, distinta do **Asset Catalog** (ADR-014, ativos
versionados) e do **catálogo de capabilities** (ADR-009).

**D13.10 — O Runtime emite eventos, não os define.** Nos pontos de transição o runtime é a **fonte** dos
eventos canônicos da ADR-012 (referência, não redefinição):

| Transição no runtime | Evento (ADR-012) |
|---|---|
| `repo.create(PENDING)` | `PlanCreated` |
| `ApprovalDecision` resolvida (N1/N2) | `PlanApproved` (ou negação) |
| plano `→ EXECUTING` | `ExecutionStarted` |
| cada tool despachada pelo Executor | `CapabilityInvoked` |
| item bloqueado por capability/HILT | `PolicyDenied` |
| plano `→ DONE/PARTIAL/FAILED` | `ExecutionCompleted` |
| runbook concluído | `RunbookCompleted` |

**D13.11 — Persistência com transições guardadas é a base da idempotência.** Toda mudança de status (plano
ou item) é um `UPDATE ... WHERE status = ANY(expected)` (ou o equivalente in-memory): a guarda é o **ponto de
idempotência**. `updated_at` na entrada em `EXECUTING` é o **relógio do TTL** do `reconcile_orphans`. Isso
elimina o TOCTOU de dupla execução (G2) sem locks distribuídos.

## Consequences

- **+** Formaliza um runtime **que já roda e é testado**; documenta as garantias (G1–G8) sem reescrever nada.
- **+** Resume-safety e anti-TOCTOU vêm de **transições guardadas** — sem locks distribuídos, testável in-memory
  com o mesmo contrato do Postgres.
- **+** Desacopla **política** (ADR-005/007/009) de **mecanismo** (este runtime): o risco/idempotência migra
  para metadata do catálogo sem tocar a máquina de estados.
- **+** GAPs (Scheduler, Memory, Risk/Policy engine) ficam **nomeados e posicionados**, prontos para as
  próximas ADRs encaixarem.
- **−** Retry/resume de WRITE fica **bloqueado** até `contract.execution.idempotent` existir no catálogo e o
  gateway honrar `Idempotency-Key` (dívida rastreada em D13.7).
- **−** Sem Scheduler, disparos por tempo/evento e o TTL `PENDING → EXPIRED` **não são automáticos** hoje.
- **−** Sem Memory, cada run recomeça sem contexto durável além do plano persistido (curadoria manual do input).
- **−** O risco é **derivado** no `CapabilityResolver` (estrutural por owner de namespace), divergente do alvo
  ADR-009 (risco no catálogo) — dupla fonte transitória até a ingestão do catálogo.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|---|---|
| **Plano gerado por LLM livre** (sem runbook) | Fallback "genérico" silencioso (problema real do agente de marketing); sem DAG validável, sem `required`, sem versão. O runbook versionado + enum fechado é auditável. |
| **Idempotência por `Idempotency-Key` no gateway** | Gateway `platform-mcp` **não** deduplica writes (verificado). Enquanto não honrar, seria falsa segurança. Guardas + `resume_writes_safe=False` são corretos hoje. |
| **Locks distribuídos p/ concorrência** | Transições guardadas (`UPDATE ... WHERE status ∈ expected`) já dão anti-TOCTOU sem a operação/latência de um lock manager. |
| **Retry cego de WRITE** | Duplica side-effect num gateway sem dedupe. WRITE órfão ⇒ `NEEDS_RECONFIRM` (humano decide) é o correto. |
| **Um único status booleano (ok/erro) por plano** | Perde `PARTIAL` vs `FAILED` (via `required`) e `unanswered` (HILT) — informação que o humano precisa. |
| **Risk tier num allow-list nominal de tools** | Frágil (esquece `push_to_registry`, `merge_branch`); derivação estrutural por owner (hoje) e metadata do catálogo (alvo) são robustas. |
| **Scheduler/Memory embutidos no Executor agora** | Inflaria o Executor e misturaria "quando roda" com "como roda". Melhor como componentes próprios (D13.8/D13.9). |

## Open questions

- **Scheduler:** onde vive o disparo por evento — assinatura direta do Kafka (`dataforall-kafka`, ADR-012) ou
  um poller? Quem detém o relógio do TTL de aprovação (`PENDING → EXPIRED`)?
- **Memory:** escopo e retenção (sessão × projeto × tenant); é derivada de eventos (ADR-012) ou store própria?
  Fronteira exata com o Asset Catalog (ADR-014).
- **Ingestão de `contract.execution.idempotent`:** o Planner lê do catálogo (ADR-009) em build-time ou o
  Executor consulta em run-time? Cache/invalidância.
- **Retry de WRITE idempotente:** política (nº de tentativas, backoff) quando `idempotent=true` — reusa a de
  READ ou é própria por Operation (`retry_policy` do contrato, ADR-009 D9.4)?
- **Motor de Risk/Policy formal separado (GAP):** quando o risco sai do `CapabilityResolver` para o catálogo,
  o runtime passa a ser **puro consumidor** — como versionar essa migração sem janela de dupla-verdade?
- **Concorrência entre runs:** granularidade do serial/paralelo (por sessão? por recurso da ADR-009?).

## References

- ADR-012 (Event Model) — eventos que o runtime **emite** (D13.10); não redefinidos aqui.
- ADR-009 (Capability Registry) — `contract.execution.idempotent`/`risk`/`authz` que o runtime **lê**
  (D13.7); nota de aterramento sobre o gateway sem dedupe de writes (D9.8).
- ADR-007 (Capability Model) — risk tiers que dirigem N1/N2 e TTL; ADR-005 (PEP/PDP + HILT) — política de
  aprovação e output/redaction que o runtime aplica; ADR-004 (capability token) — correlação por run/session.
- `platform-dev-agent`: `pipeline.py` (`AutonomousPipeline`), `plan/builder.py`, `runbook/dag.py`,
  `plan/approval.py`, `plan/executor.py`, `plan/repository.py` + `plan/repository_pg.py`, `budget.py`,
  `capability.py`, `runbook_selector.py`, `core/config.py` (`resume_writes_safe`, tetos por run).
- `PLATFORM_DEV_AGENT_SPEC.md` (§4 resume/idempotência, §6 persistência) · `docs/REAL_GATEWAY_E2E.md`.
- Prior-art: Temporal/Cadence (workflow durável + máquina de estados), Kahn (topo-sort), Saga/compensation
  (WRITE não-idempotente), OPA/Cedar (política como metadata, via ADR-009).
