# ADR-012 — Event Model

**Status:** Proposed (V1) · **Date:** 2026-07-05 · **Authors:** caiog
**Contexto compartilhado:** `MCP_ADR_INDEX.md` · **Relacionadas:** ADR-013 (Runtime — emite os eventos), ADR-005 (PEP/PDP — origem de `PolicyDenied`), ADR-009 (Platform Catalog — origem de `CapabilityInvoked`), ADR-014 (Asset Model — emissora dos eventos `Asset*` de lifecycle), ADR-006 (transporte/session binding — `session_id`), ADR-007 (risk/HILT — `ApprovalGranted/Denied`), ADR-003 (identidade — `actor`)

## Context

O runtime do `platform-dev-agent` já executa o pipeline autônomo `plan → approve → execute`
(PlanBuilder, ApprovalGate N1/N2, PlanExecutor com transições guardadas e resume-safe, RunBudget,
CapabilityResolver/Enforcer, RunbookSelector, redaction). Cada uma dessas transições é hoje um **estado
interno** — visível no log, no PlanRepository (Postgres) e no gateway, mas **não publicado** num barramento
canônico. Consequências:

1. **Auditoria fragmentada.** Quem aprovou o quê, qual capability rodou, o que a policy negou — está
   espalhado em logs de vários componentes, sem um envelope comum nem uma ordem de eventos confiável.
2. **Sem plano de leitura compartilhado.** Analytics (custo/latência por domínio), observabilidade (traces,
   métricas), timeline de execução (UX) e o audit central (ADR-005) reconstroem o mesmo estado de formas
   diferentes. Não há **contrato**.
3. **Acoplamento por polling.** Consumir "o que aconteceu" hoje significa ler o PlanRepository ou o log de
   cada MCP — acoplamento ponto-a-ponto que não escala com a Fase-6 (Control Plane).

Já existe fundação: **`dataforall-kafka` roda** (container `apache/kafka` KRaft, listener externo `:9095`,
`KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"` — tópicos são **provisionados**, não criados ad-hoc). Falta o
**contrato de eventos**: a taxonomia canônica, o envelope e o transporte. Este ADR **não** especifica os
componentes internos do runtime (ADR-013 — aqui só o **contrato do que ele emite**) nem redefine o PDP
(ADR-005 — aqui só o **evento** que o PDP produz).

## Decision

**D12.1 — Existe um Event Model canônico, source-of-truth do "o que aconteceu".** Todo componente do Control
Plane que produz um fato relevante o publica como **evento imutável** no barramento, no envelope padrão
(D12.2), sob um `type` da taxonomia canônica (D12.3). Consumidores (audit, analytics, observability,
timeline) **derivam** seu estado desses eventos — não fazem polling ponto-a-ponto. Eventos descrevem **o
que já ocorreu** (past tense, fato) — não são comandos.

**D12.2 — Envelope (estilo CloudEvents 1.0).** Todo evento carrega o mesmo envelope. Os campos de contexto
(`type`, `source`, `subject`, `time`, atributos de correlação) são **provider-agnósticos e estáveis**; o
`data` é específico do `type`.

```yaml
# --- CloudEvents context attributes (estáveis, indexáveis) ---
specversion: "1.0"
id: 01J8Z9K7Q2R3S4T5V6W7X8Y9Z0        # ULID — único por evento, ordenável no tempo
type: com.dataforall.execution.completed  # da taxonomia canônica (D12.3), reverse-DNS
source: /platform-dev-agent/executor      # componente emissor (URI-reference)
subject: run/01J8Z...                      # a entidade a que o evento se refere (run/plan/task id)
time: "2026-07-05T14:32:10.512Z"           # RFC 3339 UTC — quando o fato ocorreu
datacontenttype: application/json

# --- Extension attributes (correlação — OBRIGATÓRIOS, D12.4) ---
tenant_id: acme                            # tenant dono do fato (particionamento — D12.6)
session_id: sess_7f3a...                   # sessão MCP (ADR-006) — null p/ eventos de sistema
correlation_id: run_01J8Z...               # amarra todos os eventos de UMA execução/plano
causation_id: 01J8Z9K...                   # id do evento que causou este (cadeia causal; null se raiz)

# --- Payload específico do type ---
data: { ... }                              # JSON Schema por type (D12.3)
```

Regras do envelope:
- **`id`** é ULID (ordenável, sem coordenação) e **globalmente único** → chave de idempotência para o
  consumidor (dedup at-least-once, D12.7).
- **`type`** é reverse-DNS `com.dataforall.<aggregate>.<past-tense>` — estável e versionável (D12.8).
- **`subject`** referencia a entidade (`run/…`, `plan/…`, `task/…`, `capability/…`) para filtro barato.
- **`data` nunca contém segredo nem PII crua** — passa pela mesma redaction do runtime (D12.9).

**D12.3 — Taxonomia canônica de eventos (V1).** Treze `type`s de execução/policy + um bloco reservado de **seis
`type`s de lifecycle de asset** (ADR-014), agrupados por *aggregate*. Cada linha fixa o **emissor** (a ADR
dona) e o `data` mínimo. `correlation_id` = id do run em todos (ou id da transição de asset, p/ os de asset).

| `type` (curto) | reverse-DNS | Emissor (ADR) | `data` mínimo |
|---|---|---|---|
| `PlanCreated` | `com.dataforall.plan.created` | Runtime/Planner (013) | `plan_id, run_id, goal, runbook_id?, task_count, dag_ref` |
| `PlanApproved` | `com.dataforall.plan.approved` | Runtime/Approval (013) | `plan_id, run_id, level(N1\|N2), auto:bool` |
| `ApprovalGranted` | `com.dataforall.approval.granted` | Runtime/Approval (013) | `plan_id, run_id, level, approver(actor), scope` |
| `ApprovalDenied` | `com.dataforall.approval.denied` | Runtime/Approval (013) | `plan_id, run_id, level, approver(actor), reason` |
| `ExecutionStarted` | `com.dataforall.execution.started` | Runtime/Executor (013) | `run_id, plan_id, budget_ref, resume:bool` |
| `TaskStarted` | `com.dataforall.task.started` | Runtime/Executor (013) | `run_id, task_id, operation_id, tool_ref, attempt` |
| `TaskFinished` | `com.dataforall.task.finished` | Runtime/Executor (013) | `run_id, task_id, status(ok\|failed\|skipped), duration_ms, error?` |
| `ExecutionCompleted` | `com.dataforall.execution.completed` | Runtime/Executor (013) | `run_id, plan_id, status(succeeded\|failed\|aborted), tasks_ok, tasks_failed, budget_spent` |
| `CapabilityInvoked` | `com.dataforall.capability.invoked` | Catalog/PEP boundary (009/005) | `run_id?, operation_id, tool_id, provider_id, authz(read\|write), risk_level, blast_radius, outcome(ok\|error), latency_ms` |
| `PolicyDenied` | `com.dataforall.policy.denied` | PDP (005) | `run_id?, operation_id?, actor, required_scope, reason(scope\|purpose\|mandate\|risk\|hilt), rule_id?` |
| `RiskRejected` | `com.dataforall.risk.rejected` | Runtime/Risk gate (013) | `run_id, operation_id, risk_level, blast_radius, reason` |
| `RunbookCompleted` | `com.dataforall.runbook.completed` | Runtime/Executor (013) | `run_id, runbook_id, status, steps_total, steps_ok, duration_ms` |
| `DeploymentCompleted` | `com.dataforall.deployment.completed` | Provider/Delivery via runtime (013) | `run_id, service, environment, version, status, provider_id` |

**Bloco de lifecycle de asset (ADR-014 é a emissora/dona da semântica; este ADR é dono do envelope/transporte):**

| `type` (curto) | reverse-DNS | Emissor (ADR) | `data` mínimo |
|---|---|---|---|
| `AssetPublished` | `com.dataforall.asset.published` | Asset Catalog (014) | `asset_ref, kind, version, owner` |
| `AssetPromoted` | `com.dataforall.asset.promoted` | Asset Catalog (014) | `asset_ref, kind, version, from(draft), to(active), approver(actor)` |
| `AssetDeprecated` | `com.dataforall.asset.deprecated` | Asset Catalog (014) | `asset_ref, kind, version, superseded_by?, reason?` |
| `AssetSunset` | `com.dataforall.asset.sunset` | Asset Catalog (014) | `asset_ref, kind, version, sunset_at, superseded_by` |
| `AssetDeprecatedUsed` | `com.dataforall.asset.deprecated_used` | Asset Catalog (014) | `asset_ref, kind, version, used_by(run_id\|asset_ref)` |
| `AssetValidationFailed` | `com.dataforall.asset.validation_failed` | Asset Catalog (014) | `asset_ref, kind, version, reason(owner\|semver\|relation), detail` |

Notas de fronteira (contrato, não redefinição):
- **Bloco de asset** (`Asset*`): a **ADR-014 é a emissora e dona da semântica** dessas transições de
  lifecycle (D14.11); **este** ADR possui o **envelope e o transporte** (o `data` acima é o shape mínimo, o
  gatilho de cada transição é da ADR-014 D14.3/D14.8).
- **`CapabilityInvoked`** é emitido na **borda de execução** (onde a Operation do catálogo ADR-009 vira
  chamada de Tool, sob o PEP ADR-005). Este ADR só fixa o **shape**; a semântica de Operation/Tool/risk é da
  ADR-009 e o gate é da ADR-005.
- **`PolicyDenied`** é o evento que o **PDP (ADR-005)** produz ao negar; este ADR não define a lógica de
  decisão, só o envelope do fato.
- **`RiskRejected`** ≠ `PolicyDenied`: o primeiro é rejeição pelo **risk gate** do runtime (blast radius /
  nível), o segundo é negação de **policy** (scope/purpose/mandate/HILT).

**D12.4 — Correlação obrigatória por três eixos.** Todo evento carrega `tenant_id`, `session_id` (quando
originado de sessão MCP — ADR-006) e `correlation_id`. O `causation_id` (opcional) forma a **cadeia causal**:
`PlanCreated → PlanApproved → ExecutionStarted → TaskStarted → CapabilityInvoked → TaskFinished →
ExecutionCompleted`, todos com o **mesmo `correlation_id` = `run_id`**. Isso permite reconstruir uma execução
inteira (timeline/audit) sem join ambíguo.

**D12.5 — Transporte: Kafka (`dataforall-kafka`).** O barramento é o Kafka que já roda (KRaft, `:9095`
externo). Tópicos são **provisionados explicitamente** (`AUTO_CREATE_TOPICS_ENABLE=false` — verificado). Um
tópico por *aggregate* (não um por `type`) — granularidade que casa com os consumidores sem explodir a
topologia:

| Tópico | `type`s | Retenção sugerida |
|---|---|---|
| `platform.plan.v1` | `PlanCreated`, `PlanApproved` | 30 d |
| `platform.approval.v1` | `ApprovalGranted`, `ApprovalDenied` | **compact + 1 ano** (trilha de auditoria) |
| `platform.execution.v1` | `ExecutionStarted`, `TaskStarted`, `TaskFinished`, `ExecutionCompleted`, `RunbookCompleted` | 30 d |
| `platform.capability.v1` | `CapabilityInvoked` | 90 d (analytics de uso/custo) |
| `platform.policy.v1` | `PolicyDenied`, `RiskRejected` | **1 ano** (auditoria de segurança) |
| `platform.delivery.v1` | `DeploymentCompleted` | 1 ano |
| `platform.asset.v1` | `AssetPublished`, `AssetPromoted`, `AssetDeprecated`, `AssetSunset`, `AssetDeprecatedUsed`, `AssetValidationFailed` | **1 ano** (trilha de governança de asset — ADR-014) |

O sufixo `.v1` no **nome do tópico** carrega a versão *major* do contrato (D12.8). Produtor serializa JSON
(`datacontenttype: application/json`) com os context attributes como **headers Kafka** (indexáveis) e o
envelope completo no *value* (self-contained para replay).

**D12.6 — Particionamento por tenant.** A **chave de partição é `tenant_id`**. Garante (a) ordem por tenant
dentro do tópico — os eventos de um mesmo `run` de um tenant chegam ordenados; (b) isolamento de throughput;
(c) base para futuro *tenant-level ACL*/quota. Ordenação **global** entre tenants **não** é garantida (nem
necessária — o `time`/`id` ULID reordena na leitura quando preciso).

**D12.7 — Entrega at-least-once; consumidores idempotentes por `id`.** O barramento é at-least-once; um
evento pode ser reentregue. Consumidores **deduplicam por `id` (ULID)** — obrigatório. Produtores emitem
**após** o fato ter sido durável (ex.: `ExecutionCompleted` só depois do estado persistido no
PlanRepository) → não há evento "fantasma" de algo que não aconteceu. Ordenação é garantida só **por
partição** (por tenant); consumidores que precisam de ordem causal usam `causation_id`/`time`.

**D12.8 — Versionamento do contrato.** Mudanças **retrocompatíveis** (campo opcional novo no `data`) → mesma
`v1`. Mudanças **quebra-contrato** (remover/renomear campo, mudar tipo) → **novo tópico `.v2`** e novo
`type` major; produtor pode *dual-write* durante a transição. O `specversion` do CloudEvents fica fixo em
`1.0`; a versão do **nosso** payload é o sufixo do tópico + (opcional) `dataschema` apontando ao JSON Schema
no catálogo (ADR-011).

**D12.9 — Redaction antes de publicar.** O `data` passa pela **mesma redaction** que o runtime já aplica a
outputs (segredos, tokens, PII). Regra: eventos carregam **referências e metadados** (ids, contagens,
status, latências), **não** payloads de ferramenta crus. Ex.: `TaskFinished.error` é mensagem redigida +
código, não o stack/output bruto.

**D12.10 — Consumidores canônicos (planos de leitura, desacoplados).** Quatro consumidores de 1ª classe, cada
um com seu *consumer group*; nenhum é dono do evento (o barramento é):

| Consumidor | Consome | Deriva |
|---|---|---|
| **Audit** (ADR-005 audit central) | `approval.v1`, `policy.v1`, `capability.v1`, `delivery.v1` | trilha imutável quem-fez-o-quê / negações / mandatos |
| **Analytics** | `capability.v1`, `execution.v1` | custo/latência/uso por domínio, operação, tenant, provider |
| **Observability** | todos | traces (via `correlation_id`→span), métricas (taxa de falha, HILT, budget), alertas |
| **Timeline** (UX) | `plan.v1`, `execution.v1`, `approval.v1` | linha do tempo de um `run` para o usuário (plan→approve→execute) |

## Consequences

- **+** Contrato **único** para auditoria/analytics/observabilidade/timeline — para de reconstruir estado
  ponto-a-ponto (resolve o gap da Fase-4 do rollout da ADR-009).
- **+** Envelope estilo CloudEvents → interоperável, versionável, indexável por headers Kafka; adota
  prior-art em vez de formato caseiro.
- **+** `correlation_id`/`causation_id` reconstroem uma execução inteira → base direta de tracing e da
  timeline de UX.
- **+** Desacoplamento produtor↔consumidor (consumer groups) → novos consumidores (ex.: FinOps, SIEM) sem
  tocar no runtime.
- **+** Reaproveita `dataforall-kafka` já em pé; particionar por tenant prepara ACL/quota por tenant.
- **−** At-least-once obriga **todo** consumidor a deduplicar por `id` (disciplina de implementação).
- **−** Ordem global entre tenants não é garantida — consumidores que a assumirem quebram (mitigado por
  `time`/`causation_id`).
- **−** Provisionamento de tópicos é manual (`AUTO_CREATE=false`) → passo de operação/IaC a manter.
- **−** Redaction no caminho de publicação adiciona latência/custo ao emissor (aceitável; evita vazamento).
- **−** Versionamento por tópico (`.v2`) implica *dual-write* transitório nas quebras de contrato.

## Alternatives Considered

| Alternativa | Motivo de rejeição |
|---|---|
| **Sem barramento — consumidores leem o PlanRepository/logs** | Acoplamento ponto-a-ponto; sem contrato nem ordem; não escala com novos consumidores. |
| **Envelope caseiro (JSON ad-hoc por emissor)** | Cada emissor inventa campos; sem correlação padronizada; reinventa o que CloudEvents já resolve. |
| **Um tópico por `type`** (13+ tópicos) | Explode a topologia e o particionamento; consumidores multiplexam N assinaturas para uma timeline. Um tópico **por aggregate** cobre o mesmo com menos operação. |
| **Um único tópico `platform.events`** | Mistura retenções/ACLs (auditoria 1 ano × execução 30 d); um consumidor de analytics lê tudo. Por-aggregate separa retenção e política. |
| **Particionar por `run_id`** | Cardinalidade altíssima e sem isolamento de tenant; ordem por run já vem da mesma partição do tenant. |
| **Exactly-once (transações Kafka)** | Custo/complexidade desproporcional; at-least-once + dedup por ULID entrega o mesmo efeito prático. |
| **Barramento novo (NATS/RabbitMQ)** | `dataforall-kafka` já roda e é o padrão da plataforma; introduzir outro broker é custo sem ganho. |
| **Eventos como comandos (imperativos)** | Acopla emissor↔consumidor e reintroduz orquestração; eventos são **fatos** (past tense), consumidores reagem. |

## Open questions

- **Schema registry:** JSON Schema versionado no catálogo (ADR-011) × Confluent Schema Registry × Avro? (V1
  usa JSON + `dataschema` opcional; formalizar a fonte da verdade do schema é da ADR-011.)
- **`actor` no envelope:** modelar identidade do aprovador/chamador (ADR-003) como extension attribute
  estruturado (`actor.class`, `actor.id`) × campo dentro de `data`? (V1 põe em `data`.)
- **DLQ / poison events:** tópico de *dead-letter* por aggregate e política de reprocesso — definir na Fase-4.
- **Retenção fina × compliance:** LGPD pode exigir *purge* seletivo por tenant em tópicos de 1 ano
  (compact + tombstone por `tenant_id`?) — depende da política de retenção de dados pessoais.
- **Emissão do `CapabilityInvoked`:** no PEP (ADR-005) ou na borda do catálogo (ADR-009)? Fronteira a
  cravar junto com os donos de 005/009 (aqui fixado apenas o *shape*).
- **Ingestão sync × async:** emitir inline no caminho crítico (latência) × outbox transacional no
  PlanRepository → relay para o Kafka (garante durabilidade antes do publish). Recomendação: **outbox** para
  eventos de estado durável (D12.7); detalhar na ADR-013.

## References

- **ADR-013 (Runtime)** — quem **emite** a maioria destes eventos (Planner/Approval/Executor); este ADR fixa
  só o contrato do que ele emite, não os componentes internos.
- **ADR-005 (PEP/PDP)** — origem de `PolicyDenied` e consumidor **Audit**; este ADR não redefine a decisão de
  policy, só o envelope do fato.
- **ADR-009 (Platform Catalog)** — origem semântica de `CapabilityInvoked` (Operation/Tool/risk); a Fase-4 do
  rollout da ADR-009 ("Events no Kafka") é **este** ADR.
- **ADR-014 (Asset Model)** — **emissora/dona da semântica** dos eventos `Asset*` de lifecycle (D14.11); este
  ADR possui o envelope/transporte e o tópico `platform.asset.v1`.
- **ADR-006 (Transportes)** — origem do `session_id` (session binding) no envelope.
- **ADR-007 (Capability Model)** — `risk_level`/HILT por trás de `ApprovalGranted/Denied` e `RiskRejected`.
- **ADR-003 (Identidade)** — modelo do `actor` (aprovador/chamador) referenciado no `data`.
- `dataforall-kafka` — broker `apache/kafka` KRaft já em pé (`deploy/docker-compose.infra.yml`, `:9095`,
  `AUTO_CREATE_TOPICS_ENABLE=false`).
- Prior-art: **CloudEvents 1.0** (envelope/context attributes), **ULID** (ids ordenáveis), Kafka
  (log particionado, compaction), padrão **Transactional Outbox** (durabilidade do produtor).
