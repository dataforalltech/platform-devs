# ADR 0001 — Servidor separado; Phase 1 read-only como fundação para allocator (Phase 2)

**Data**: 2026-05-06 (criado) · 2026-05-07 (atualizado com status Phase 2a/2b/2c/2d/2e/2f/2g/2h)
**Status**: Aceito (Phase 1 + Phase 2a + Phase 2b + Phase 2c + Phase 2d + Phase 2e + Phase 2f + Phase 2g + Phase 2h)
**Decisor**: @caiog
**Implementação**: Phase 1 (#11), Phase 2a (#12), Phase 2b (#13), Phase 2c (#14), Phase 2d (#15), Phase 2e (#16), Phase 2f (#17), Phase 2g (#18), Phase 2h (este PR)

## Contexto

Precisamos de tooling MCP para operações de infraestrutura (terraform, VMs Azure, policy scan, cost estimate, redes, segredos). Duas dimensões de decisão:

1. **Onde colocar**: tools no `ai-governance-mcp-server` existente vs. servidor separado.
2. **Que operações expor**: somente read-only ou incluir mutação (apply, destroy)?

## Decisão

**Servidor separado** chamado `infra-mcp-server`. **Apenas operações read-only no Phase 1** (`terraform plan/validate/fmt`, `checkov`, `infracost`). Operações de mutação (`apply`, `destroy`, edição de state) ficam **explicitamente fora do escopo** desta versão.

## Por quê servidor separado

| Critério | ai-governance | infra-mcp |
|---|---|---|
| Risco operacional de bug | Baixo (read-only de KB textual + grafo) | Alto (toca em CLIs com side effects, mesmo read-only — `terraform plan` baixa providers, faz API call ao Azure) |
| Audit trail | suggestion_store, opcional | Obrigatório por chamada (cada plan custa rate limit Azure) |
| Credenciais necessárias | Nenhuma | Azure SP, Terraform state backend creds, Infracost API key |
| Cadência de release | Trimestral (política muda devagar) | Provavelmente quinzenal (terraform CLI evolui rápido, providers Azure mudam) |
| Escopo do enable em clients | Amplo (todo agente quer ver política) | Restrito (só agentes de infra autorizados) |
| Kill-switch granular | N/A | Necessário (`gh secret remove` + remover MCP do client = paralisar infra ops sem afetar governança) |

Servidor separado permite gestão independente de cada eixo. Compartilham a stack (Python + mcp SDK + stdio + Pydantic) e podem coexistir sem fricção.

## Por quê apenas read-only no Phase 1

A política `cicd-deploy.md §4` do `ai-governance-mcp-server` lista 10 HARD STOPS específicos para CI/CD. Vários deles tornam mutação automatizada via MCP **impraticável** sem aprovação humana:

- "Mudança em recurso `lifecycle.prevent_destroy = true`" → exige ADR + decisão humana.
- "checkov/tfsec retornam HIGH/CRITICAL" → bloqueio HARD.
- "infracost delta > threshold" → exige aprovação humana.
- "terraform destroy" → apenas com `--target` + confirmação humana no terminal.
- "Edição direta de tfstate" → proibido em automação.
- "Apply em prod sem PR merged" → proibido.

Implementar `terraform_apply` aqui significaria:

1. Replicar todos os HARD STOPS do `cicd-deploy.md` no servidor.
2. Mecanismo de aprovação humana out-of-band (não-trivial via MCP stdio).
3. Auditoria forense de quem disparou o quê e quando.
4. Idempotência e rollback automatizado em caso de falha.

Cada um desses é projeto próprio. Phase 1 entrega o que **um agente de IA pode fazer com segurança**: descobrir, validar, estimar, sugerir. **Aplicar é humano**.

## Tools no Phase 1

Cada tool é wrapper de subprocess sobre uma CLI externa, com captura de output estruturado:

| Tool | CLI subjacente | O que retorna |
|---|---|---|
| `terraform_validate` | `terraform validate -json` | Erros/warnings de sintaxe e tipo |
| `terraform_fmt_check` | `terraform fmt -check -diff` | Lista de arquivos não formatados + diff |
| `terraform_plan` | `terraform plan -no-color -out=tfplan -detailed-exitcode` | Resumo: N to add/change/destroy + path do plan binary |
| `terraform_show_plan` | `terraform show -json tfplan` | Plan em JSON estruturado para análise |
| `policy_scan_checkov` | `checkov -d <path> -o json` | Findings categorizados por severidade |
| `cost_estimate_infracost` | `infracost diff --path tfplan` | Delta de custo + breakdown por recurso |

## Tools NÃO entregues no Phase 1 (mas planejadas para Phase 2 — allocator)

A versão do ADR de 2026-05-06 inicialmente declarava `terraform_apply` "fora do
escopo Phase 1". A direção foi refinada: **mutação é necessária**, mas
**não direta** — agentes não rodam `terraform apply` por conta própria.

- `terraform_apply` — Phase 2, **mediado pelo allocator** (ver §"Phase 2").
- `terraform_destroy` — Phase 2, somente via lifecycle do allocator (lease expirou + GC).
- `terraform_state_*` — fora do escopo permanente. Apenas humano em runbook.
- `azure_vm_lifecycle` (start/stop/restart) — Phase 2, parte do allocator.
- `azure_keyvault_read` (valor de segredo) — Phase 3, exige design de não-vazamento (token ID em vez de valor).
- `azure_network_acl_modify` — fora do escopo. Mudança em rede continua humana.

## Phase 2 — VM allocator (designed, not implemented)

Phase 2 transforma o servidor de "wrapper de CLIs read-only" em **allocator
de recursos compartilhados**. Princípio: agentes **não criam infra** — eles
**solicitam capacidade** e o allocator decide se aproveita uma VM existente,
provisiona uma nova, ou enfileira/recusa.

### Modelo de domínio

| Entidade | Função |
|---|---|
| `VMSpec` | Tipo de recurso (cpu-small, gpu-a100, high-mem, etc.) — catálogo fechado |
| `VMRequest` | Pedido do agente: spec + duração estimada + prioridade + sharing policy + dono |
| `VMLease` | Concessão: lease_id, vm_id, expira_em, dono, conexão (handed-off seguro) |
| `VMPool` | Inventário: VMs ativas, leases atuais, capacidade restante |
| `AllocationStrategy` | Lógica: try-share-first → provision-if-budget-ok → queue-or-deny |

### Fluxo

```
Agente:  request_vm(spec=cpu-small, duration_min=60, exclusive=false, priority=low)
   ↓
Allocator:
  1. Há VM compatível com slot livre + cliente atual aceita compartilhar? → assign lease
  2. Pode provisionar nova sem furar budget/quota? → terraform_apply via Phase 1 tools (já validados)
  3. Else → enfileira (priority queue) ou DENY com motivo
   ↓
Resposta: VMLease com job_id; conexão entregue separado quando READY
```

### Tools planejadas

- `request_vm(spec, duration_min, exclusive, priority, owner)` → `VMLease | QueuedRequest | DeniedRequest`
- `extend_lease(lease_id, additional_min)` → bump expiry (com cap de duração total)
- `release_lease(lease_id)` → libera slot, dispara GC se VM órfã
- `get_lease(lease_id)` → status + connection info (quando READY)
- `list_my_leases(owner)` → leases do agente
- `list_pool()` → admin/visibility (todas VMs, todas leases)
- `query_capacity(spec)` → "haveria slot sem provisionar?" (planejamento sem efeito)

### Hard stops do allocator

1. **Cost cap** — quota de gasto $/hora por agente + total/dia.
2. **Concurrent leases** — limite por agente (default 3 ativos simultâneos).
3. **Spec whitelist** — GPU/high-mem exigem aprovação humana out-of-band.
4. **Lease max duration** — cap absoluto (default 24h; renovação ≤ N vezes).
5. **Auto-release** — se não houver heartbeat do agente em X min, libera.
6. **Provisão de network** — VMs novas SEMPRE em VNet/subnet pré-aprovada;
   nunca cria nova VNet ou abre regra NSG.
7. **Image pinning** — apenas imagens base da allowlist (registries internos).

### Por quê o allocator usa as tools Phase 1 internamente

O allocator **não duplica** lógica de provisionamento. Ele orquestra:

- `terraform_plan` — quando precisa provisionar, gera plan e valida.
- `policy_scan_checkov` — verifica que o plan não viola policy antes de aplicar.
- `cost_estimate_infracost` — confirma que o delta cabe no budget restante.
- `terraform_apply` (novo, Phase 2) — só dispara depois das 3 etapas verdes E
  com lease já registrado. Se qualquer etapa falhar, rejeita o request.

Phase 1 é fundação. Phase 2 é a UX que usa essa fundação.

### State store (Phase 2a)

Allocator precisa de estado persistente: leases ativas, pool atual, fila.
Decisão de tecnologia adiada para Phase 2a:

- **SQLite local** (mesmo modelo do `suggestion_store` em ai-governance) —
  simples, audit via git se commitado, single-writer suficiente para v0.
- **Postgres** quando múltiplos servidores allocator rodarem em HA —
  longe.

### Concorrência

Single-writer SQLite + lock por arquivo é suficiente para Phase 2a.
Quando >50 requests/min, migrar para fila persistente (Redis Streams ou Azure
Service Bus) — Phase 2c.

### Fora do escopo do allocator (mesmo Phase 2)

- Provisionamento de redes (VNets, subnets, NSGs) — humano em runbook.
- IAM (criação de SP, role assignments) — humano + revisão de segurança.
- Modificação de DNS, certificados — fora.
- Persistência de dados nas VMs alocadas — VMs efêmeras por design;
  workload precisa salvar resultado em storage externo antes do release.

### Phase 2 incremental

| Sub-phase | Entrega | Status |
|---|---|---|
| **2a** | **Domain model + in-memory pool + 7 tools (request_vm/get/release/extend/list_my_leases/list_pool/query_capacity); hard stops; GC de leases expirados** | **✅ entregue** |
| **2b** | **SQLite persistence: `AllocatorStore` → SQLite-backed; leases/VMs sobrevivem restart; `INFRA_DB_PATH`; 10 testes de persistência** | **✅ entregue** |
| **2c** | **Provisioner injetável: `ImmediateProvisioner` (default/testes) + `TerraformProvisioner` (terraform real em background thread); lease PENDING→ACTIVE; módulo stub `cpu-small`; `INFRA_TF_MODULES_ROOT`; 13 testes** | **✅ entregue** |
| **2d** | **Módulos terraform multi-cloud reais: `aws/{cpu-small,cpu-medium}`, `azure/{cpu-small,cpu-medium}`, `gcp/{cpu-small,cpu-medium}`; Ubuntu 20.04 LTS; state isolation via `-state=states/<vm_id>.tfstate`; sem terraform destroy automático ainda** | **✅ entregue** |
| **2e** | **`TerraformProvisioner.destroy()` + `ImmediateProvisioner.destroy()` + `AllocatorStore._schedule_destroy()` (3 pontos de disparo: release_lease, _on_vm_failed, _gc_expired); `cpu-large` modules (aws/azure/gcp); 11 novos testes** | **✅ entregue** |
| **2f** | **SSH key per-VM (Ed25519, Fernet, `vm_keys` SQLite, `get_lease_ssh_key` tool); módulos AWS migrados para `aws_key_pair` por VM; backend remoto (S3/AzureRM/GCS) via `INFRA_TF_BACKEND_TYPE` + workspaces; 23 novos testes (166 total)** | **✅ entregue** |
| **2g** | **6 novos módulos terraform (gpu-a100 + high-mem × 3 clouds); `TerraformProvisioner` refatorado para plan→infracost→apply; `_check_cost()` com `INFRA_COST_CAP_USD_MONTH`; 10 novos testes (176 total)** | **✅ entregue** |
| **2h** | **Priority queue (`queued_requests` SQLite) + preemption greedy (priority='high' preempta VMs com só leases low); `AllocationDecision.request_id`; `cancel_queued_request` (15ª tool); processamento automático da fila em release/ready/failed; 19 novos testes (195 total)** | **✅ entregue** |
| 2h | Priority queue + preempção de leases low-priority quando high-priority chega | aberto |

### Status Phase 2a (delivered)

**Entregue:**

- 7 tools MCP (request_vm, get_lease, release_lease, extend_lease, list_my_leases, list_pool, query_capacity)
- AllocatorStore in-memory com strategy try-share-first → provision-if-budget → queue-or-deny
- Hard stops: cost cap default $5/h, max 3 leases ativos por owner, lease cap 24h, max 3 extensões, spec whitelist sem aprovação `{cpu-small/medium/large}`
- GC automático de leases expirados em toda operação
- 60 testes cobrindo strategy, hard stops, lifecycle, sharing, capacity query
- Domain model fechado (catálogo de 5 specs, 4 status de lease, 4 status de VM)
- Logs estruturados de cada decisão de allocação

**Não entregue ainda (Phase 2b+):**

- Persistência cross-restart (SQLite) → restart do server limpa estado ← **resolvido em Phase 2b**
- Provisão real (terraform_apply) → vm_id é UUID simulado, connection_hint é mock URL
- Fila persistente → `outcome=QUEUED` é resposta de "tente de novo", não memoriza ordem
- Multi-process/multi-host → RLock single-process apenas
- SSH key handoff seguro → connection_hint atual não tem credencial
- Cost cap dinâmico via infracost → SPEC_COST_USD_PER_HOUR é tabela fixa Phase 2a

**Trade-offs aceitos para Phase 2a:**

- Simplicidade > completude. Phase 2a comprova o modelo de domínio e a UX para os agentes (request → lease com decision rationale) sem o investimento de integração com Azure. Quando agentes começarem a usar Phase 2a contra um pool simulado, descobrimos as arestas reais do contrato antes de gastar com terraform real.
- Estado em memória > durabilidade. Restart limpa tudo. Aceitável enquanto provisão é simulada — não há recurso real para "perder". Phase 2b corrige antes de 2c (provisão real).
- Heurística simples > scheduler robusto. `has_capacity_for` cap de 4 leases por VM, `try-share-first` linear no pool. Phase 2f adiciona priority queue + preempção.

### Status Phase 2b (delivered)

**Entregue:**

- `AllocatorStore` agora persiste em SQLite (`isolation_level=None` + `BEGIN/COMMIT` em mutations atômicas)
- Schema: tabelas `vms` e `leases` com índices (`idx_leases_owner`, `idx_leases_vm_id`, `idx_leases_status`)
- `db_path=":memory:"` default → testes isolados sem overhead de arquivo; API idêntica
- `INFRA_DB_PATH` em `Settings` (default `allocator.db` no cwd do processo)
- `mcp_server.py` instancia com `db_path=settings.db_path` e loga path no startup
- `close()` exposto para testes com `tmp_path` (cleanup determinístico)
- GC de leases expirados em SQL batch com terminação de VMs órfãs em única transação
- `_find_compatible_vm` via SQL puro (subquery correlated, sem loop Python sobre todas as VMs)
- 10 testes de persistência em `tests/test_allocator_persistence.py` cobrindo restart, sharing cross-restart, cost cap cross-restart, exclusive lock, multiple owners
- 1 teste adaptado (`test_expired_lease_marked_on_next_operation`) usa `store._con.execute()` para manipulação direta de expires_at no SQLite

**Não entregue ainda (Phase 2c+):**

- Provisão real (terraform_apply) → vm_id ainda é UUID simulado, connection_hint é mock URL
- Fila persistente (com retry automático quando lease libera) → `outcome=QUEUED` é ainda resposta de "tente de novo"
- Multi-process/multi-host → RLock single-process; SQLite WAL permite leitores concorrentes de mesmo processo
- SSH key handoff seguro
- Migrations automáticas de schema (Phase 2b: upgrade exige apagar `.db`; Phase 2c+ adiciona versão + migrate)

**Trade-offs aceitos para Phase 2b:**

- `isolation_level=None` (autocommit) + `BEGIN/COMMIT` explícito em vez de `with con:` — mais explícito, evita controvérsias de nesting de context managers do sqlite3 Python.
- Sem `alembic`/`migrate` ainda — schema simples com `CREATE IF NOT EXISTS`, suficiente para Phase 2b. Phase 2c adicionará quando terraform_apply criar VMs reais e dados ganharem valor de auditoria longo prazo.

### Status Phase 2d (delivered)

**Entregue:**

- Módulos terraform reais para 3 clouds × 2 specs = 6 módulos:
  - `aws/cpu-small` (t3.medium, 2 vCPU/4 GiB) e `aws/cpu-medium` (t3.xlarge, 4 vCPU/16 GiB)
  - `azure/cpu-small` (Standard_B2s, 2 vCPU/4 GiB) e `azure/cpu-medium` (Standard_D4s_v3, 4 vCPU/16 GiB)
  - `gcp/cpu-small` (e2-medium, 2 vCPU/4 GiB) e `gcp/cpu-medium` (e2-standard-4, 4 vCPU/16 GiB)
- Ubuntu 20.04 LTS em todos os módulos (OS canônico dataforalltech)
- State isolation: `-state=states/<vm_id>.tfstate` no apply + output — provisões concorrentes do mesmo spec não conflitam
- Hardening: IMDSv2 obrigatório (AWS), `disable_password_authentication` (Azure), `block-project-ssh-keys` (GCP)
- Hard stops de rede: nenhum módulo cria VPC/VNet/subnet/NSG compartilhado — apenas recursos de escopo da VM
- Todos os 132 testes existentes mantidos passando (sem testes novos: módulos .tf são infraestrutura, não código Python)

**Não entregue ainda (Phase 2e+):**

- `TerraformProvisioner.destroy()` → VMs ficam com status TERMINATED no allocator mas recurso cloud permanece até runbook manual
- Backend remoto (S3/AzureRM/GCS) → state local, não compartilhável entre instâncias do allocator
- `cpu-large`, `high-mem`, `gpu-a100` → sem módulos ainda (approvals + tipos de instância a definir)
- Migrations automáticas de schema → ainda sem alembic

**Trade-offs aceitos para Phase 2d:**

- Local backend aceito por ora. Cada instância do allocator tem seu próprio state. Para operações single-node (padrão Phase 2d), suficiente. Phase 2e migra para backends remotos com lock.
- Sem destroy automático. Risco de custo residual se o allocator reiniciar sem cleanup prévio. Mitigação: operador deve monitorar VMs tagged `ManagedBy=infra-mcp-allocator` e destruir as que não têm lease ativo no allocator.
- Nome de recursos truncado a 8 chars do vm_id (Azure/GCP com limites de nome curto). Probabilidade de colisão: 1/16^8 = negligível para a escala Phase 2d.

## Consequências

### Positivas

- Agentes podem **planejar e validar** antes de pedir apply ao humano. Reduz fricção de iteração.
- Sem credenciais Azure permanentes no MCP — apenas as ambiente do shell que o servidor herda.
- `validate_agent_decision` do `ai-governance` continua sendo o gate antes de qualquer apply manual.
- Servidor pequeno, fácil de auditar, fácil de remover de cliente em caso de incidente.

### Negativas

- Subprocess wrapping perde features ricas do SDK Python Azure (paginação, retry estruturado). Aceitável para Phase 1; quando virar real, migra para SDK por tool.
- Cada tool exige a CLI subjacente instalada no host do agente (terraform, checkov, infracost, az). Documentado em README §Pré-requisitos. Sem CLI instalada = tool retorna erro tipado, não trava sessão.
- `terraform plan` faz chamadas reais ao backend (S3/Azure Storage/etc.) e providers. Custa rate limit. Mitigação: cache curto por agente + log de cada invocação.

## Validação

- Tests com subprocess mockado garantem o contrato (input shape, error handling, truncamento de output).
- Smoke test executa as CLIs em fixture terraform mínima quando o ambiente tem os binários.
- ADR é revisitado quando: (a) primeira tentativa de adicionar `terraform_apply` é proposta, (b) >5 tools de mutação aparecem na fila, (c) integração com Azure Workload Identity for federada.

## Referências

- `ai-governance-mcp-server/knowledge-base/cicd-deploy.md` (HARD STOPS canônicos)
- `ai-governance-mcp-server/docs/decisions/adr-0001-mcp-stack-choice.md` (escolha de stack compartilhada)
