# infra-mcp-server

> MCP Server de orquestração de infraestrutura para o ecossistema `dataforalltech`.
>
> **Phase 1 ✅** — fundação read-only: wrappers estruturados sobre `terraform`, `checkov`, `infracost`.
>
> **Phase 2a ✅** — VM allocator in-memory: agentes solicitam capacidade (`request_vm(spec, duration, exclusive, priority)`), servidor decide entre **compartilhar VM existente** (otimização de custo) ou **provisionar nova** (controlado por budget/quota), retornando um `VMLease`. Provisão **simulada** nessa sub-phase — `vm_id`/connection_hint são mocks.
>
> **Phase 2b ✅** — SQLite persistence: `AllocatorStore` agora persiste leases e VMs em SQLite. Leases e pool **sobrevivem a server restart**. `INFRA_DB_PATH` controla o arquivo (default `allocator.db` no cwd; `:memory:` para testes).
>
> **Phase 2c ✅** — Provisioner injetável + terraform real: `TerraformProvisioner` provisiona VMs via `terraform init/apply/output` em background thread. Lease inicia `PENDING` e vai `ACTIVE` quando VM fica `READY` (+ `connection_hint` com endpoint SSH). `ImmediateProvisioner` (default sem `INFRA_TF_MODULES_ROOT`) mantém comportamento síncrono/instantâneo para testes. Módulo stub `terraform-modules/cpu-small/` (null_resource + output) valida o fluxo sem infra real.
>
> **Phase 2d ✅** — Módulos terraform multi-cloud reais: `aws/cpu-small`, `aws/cpu-medium` (EC2 t3.medium/xlarge); `azure/cpu-small`, `azure/cpu-medium` (Standard_B2s/D4s_v3); `gcp/cpu-small`, `gcp/cpu-medium` (e2-medium/standard-4). Ubuntu 20.04 LTS em todos. State isolation por VM via `-state=states/<vm_id>.tfstate`. Aponte `INFRA_TF_MODULES_ROOT` para a pasta do cloud desejado (`aws`, `azure` ou `gcp`).
>
> **Phase 2e ✅** — Destroy automático + cpu-large: `TerraformProvisioner.destroy()` roda `terraform destroy` em background thread quando uma VM é terminada (`release_lease` último lease, falha de provisão, GC de leases expirados). Modules `aws/cpu-large` (m5.2xlarge), `azure/cpu-large` (Standard_D8s_v3), `gcp/cpu-large` (e2-standard-8). 11 novos testes (143 total).
>
> **Phase 2f ✅** — SSH key per-VM + backend remoto: par Ed25519 gerado por VM provisionada, chave pública injetada via `TF_VAR_ssh_public_key`, privada cifrada (Fernet/AES-128) em `vm_keys` SQLite. Nova tool `get_lease_ssh_key(lease_id, owner)`. Chave deletada ao terminar VM. Módulos AWS (`aws/cpu-{small,medium,large}`) migrados de `key_name` estático para `aws_key_pair` por VM. Backend remoto (S3/AzureRM/GCS) via `INFRA_TF_BACKEND_TYPE` + workspace por VM para state isolation. 23 novos testes (166 total).
>
> **Phase 2g ✅** — Multi-spec catalog completo + infracost cost cap: 6 novos módulos terraform (`aws/gpu-a100`, `aws/high-mem`, `azure/gpu-a100`, `azure/high-mem`, `gcp/gpu-a100`, `gcp/high-mem`). `TerraformProvisioner` refatorado para fluxo `plan → infracost diff → apply <planfile>` (sem `-auto-approve` no apply). `_check_cost()` verifica `totalMonthlyCost` do infracost; se excede `INFRA_COST_CAP_USD_MONTH` → bloqueio; se binário ausente/timeout/erro → warning, não bloqueia. 10 novos testes (176 total).
>
> **Phase 2h ✅** — Priority queue + preemption: requests bloqueados pelo cost cap são persistidos na tabela `queued_requests` (SQLite) com `request_id`. Fila processada automaticamente em `release_lease`, `_on_vm_ready` e `_on_vm_failed`. Requests `priority='high'` tentam preemption greedy de VMs com apenas leases low-priority antes de enfileirar. Nova tool `cancel_queued_request(request_id)`. 19 novos testes (195 total).

## Tools (15)

### Phase 1 — terraform/policy/cost (read-only)

| Tool | CLI | O que faz |
|---|---|---|
| `terraform_validate` | `terraform validate -json` | Sintaxe + tipo |
| `terraform_fmt_check` | `terraform fmt -check -diff` | Estilo (não modifica) |
| `terraform_plan` | `terraform plan -out -detailed-exitcode` | Resumo + .tfplan binário |
| `terraform_show_plan` | `terraform show -json <plan>` | Plan estruturado |
| `policy_scan_checkov` | `checkov -d <path> -o json` | Findings + `hard_stop` se HIGH/CRITICAL |
| `cost_estimate_infracost` | `infracost diff --path <plan>` | Delta de custo + `hard_stop` por threshold |

### Phase 2a — VM allocator

| Tool | O que faz |
|---|---|
| `request_vm(spec, duration_min, owner, exclusive=False, priority="low", purpose=None, human_approved=False)` | Agente solicita capacidade. Allocator decide: lease compartilhado, nova VM (simulada), fila ou denial. Retorna `AllocationDecision` com `outcome=LEASED|QUEUED|DENIED`. |
| `get_lease(lease_id)` | Estado atual + `connection_hint`. |
| `release_lease(lease_id, by=None)` | Idempotente. VM órfã é terminada. |
| `extend_lease(lease_id, additional_min)` | Bump expiry; cap absoluto 24h totais e máx 3 extensões. |
| `list_my_leases(owner, status=None)` | Leases do agente. |
| `list_pool()` | Snapshot administrativo (VMs + custo/hora total). |
| `query_capacity(spec, owner=None)` | Planejamento sem efeito; retorna `can_satisfy_now`, `by_existing_vm`, `would_provision`, `blocked_by`. |
| `get_lease_ssh_key(lease_id, owner)` | Retorna chave privada Ed25519 PEM para SSH à VM. Requer lease ACTIVE + owner correto. Chave deletada no release. |
| `cancel_queued_request(request_id, by=None)` | Cancela request WAITING na fila (Phase 2h). `request_id` retornado por `request_vm` quando `outcome=QUEUED`. |

### Hard stops do allocator (Phase 2a)

- Cost cap default `$5/h` total no pool
- Máx 3 leases ativos por owner
- Lease máx 24h, máx 3 extensões
- Specs whitelist sem aprovação: `cpu-small`, `cpu-medium`, `cpu-large`
- Specs com aprovação humana obrigatória (`request.human_approved=True`): `gpu-a100`, `high-mem`

> 🛠️ Política operacional: [knowledge-base/infra-policy.md](knowledge-base/infra-policy.md)
> 🏛️ Por quê servidor separado: [docs/decisions/adr-0001](docs/decisions/adr-0001-readonly-only.md)
> ⚖️ HARD STOPS canônicos: [`ai-governance/cicd-deploy.md`](../ai-governance-mcp-server/knowledge-base/cicd-deploy.md)

## Tools (6, todas read-only)

| Tool | CLI | O que faz |
|---|---|---|
| `terraform_validate` | `terraform validate -json` | Sintaxe + tipo |
| `terraform_fmt_check` | `terraform fmt -check -diff` | Estilo (não modifica) |
| `terraform_plan` | `terraform plan -out -detailed-exitcode` | Resumo + .tfplan binário |
| `terraform_show_plan` | `terraform show -json <plan>` | Plan estruturado |
| `policy_scan_checkov` | `checkov -d <path> -o json` | Findings + `hard_stop` se HIGH/CRITICAL |
| `cost_estimate_infracost` | `infracost diff --path <plan>` | Delta de custo + `hard_stop` por threshold |

## Pré-requisitos

- Python ≥ 3.11
- Os binários abaixo no PATH (ou `INFRA_<TOOL>_BIN` apontando):
  - `terraform` ≥ 1.5
  - `checkov` ≥ 3.0
  - `infracost` ≥ 0.10

Sem um binário, a tool correspondente retorna `error: binary_not_found`. Sessão segue OK para outras tools.

## Instalação

```bash
cd infra-mcp-server
python -m venv .venv && source .venv/bin/activate   # ou .venv\Scripts\activate
pip install -e ".[dev]"
```

## Uso via cliente MCP

Claude Code (escopo user):
```bash
claude mcp add -s user infra-mcp -- python -m src.server.mcp_server
```

Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "infra-mcp": {
      "command": "python",
      "args": ["-m", "src.server.mcp_server"],
      "cwd": "/abs/path/to/infra-mcp-server",
      "env": { "INFRA_TERRAFORM_ROOT": "/abs/path/to/terraform/modules" }
    }
  }
}
```

## Fluxo recomendado

```
terraform_fmt_check         (estilo)
   ↓
terraform_validate          (sintaxe)
   ↓
terraform_plan              (gera .tfplan)
   ↓
terraform_show_plan         (estrutura JSON)
   ↓
policy_scan_checkov         (HARD STOP em HIGH/CRITICAL)
   ↓
cost_estimate_infracost     (HARD STOP em delta excessivo)
   ↓
Tudo verde? → PR ao humano com plan + scan + cost anexados.
Algum hard_stop? → reportar, parar.
```

## Setup por ambiente (Phase 2d)

### DEV / HML — AWS

```bash
export INFRA_TF_MODULES_ROOT=/abs/path/to/infra-mcp-server/terraform-modules/aws
# Credenciais AWS (uma das opções):
export AWS_PROFILE=dev-profile
# ou:
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=us-east-1
# Variáveis do módulo:
export TF_VAR_subnet_id=subnet-0abc1234
export TF_VAR_vpc_id=vpc-0abc1234
# TF_VAR_key_name NÃO é mais necessário — Phase 2f gera aws_key_pair por VM
export TF_VAR_region=us-east-1                  # opcional, default us-east-1
export TF_VAR_ssh_source_cidr=10.100.0.0/16     # opcional, default 10.0.0.0/8
# Para cifrar chaves SSH entre restarts:
# export INFRA_LEASE_SECRET=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

### PROD — Azure

```bash
export INFRA_TF_MODULES_ROOT=/abs/path/to/infra-mcp-server/terraform-modules/azure
# Credenciais Azure (Service Principal):
export ARM_CLIENT_ID=...
export ARM_CLIENT_SECRET=...
export ARM_TENANT_ID=...
export ARM_SUBSCRIPTION_ID=...
# Variáveis do módulo:
export TF_VAR_resource_group=rg-agents-prod
export TF_VAR_subnet_id=/subscriptions/.../resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet-prod/subnets/snet-agents
export TF_VAR_admin_ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"
export TF_VAR_location=brazilsouth               # opcional, default brazilsouth
```

### Testes — GCP

```bash
export INFRA_TF_MODULES_ROOT=/abs/path/to/infra-mcp-server/terraform-modules/gcp
# Credenciais GCP:
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
# ou: gcloud auth application-default login
# Variáveis do módulo:
export TF_VAR_project=my-gcp-project-id
export TF_VAR_network=default
export TF_VAR_subnetwork=default
export TF_VAR_ssh_user=ubuntu
export TF_VAR_ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"
export TF_VAR_zone=us-central1-a                 # opcional, default us-central1-a
# Para gpu-a100 (a2-highgpu-1g) usar zona com A100 disponível:
# export TF_VAR_zone=us-central1-c
```

> **Destroy manual de VMs**: `terraform destroy -state=terraform-modules/<cloud>/<spec>/states/<vm_id>.tfstate`
> — necessário até Phase 2e implementar `TerraformProvisioner.destroy()`.

## Variáveis de ambiente

| Var | Default | Função |
|---|---|---|
| `INFRA_LEASE_SECRET` | (auto) | Fernet key (base64, 32 bytes) para cifrar chaves SSH por VM. Se ausente, gerado por sessão (chaves perdidas em restart). Gerar: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `INFRA_TF_BACKEND_TYPE` | `local` | Backend terraform: `local` (state por VM via `-state`), `s3`, `azurerm`, `gcs` (workspaces por VM) |
| `INFRA_TF_BACKEND_CONFIG_JSON` | (none) | JSON com config do backend remoto: `{"bucket":"...","region":"us-east-1","key":"infra-mcp/terraform.tfstate"}` |
| `INFRA_COST_CAP_USD_MONTH` | (none) | Cap de custo mensal em USD por provisão via infracost diff. None → sem verificação. Requer `infracost` no PATH; se ausente → warning, não bloqueia |
| `INFRA_DB_PATH` | `allocator.db` | Caminho do banco SQLite do allocator (Phase 2b+). `:memory:` para testes sem persistência |
| `INFRA_TF_MODULES_ROOT` | (none) | Raiz dos módulos terraform por cloud: `terraform-modules/aws`, `azure` ou `gcp` (Phase 2d+). None → ImmediateProvisioner (mock) |
| `INFRA_PROVISION_TIMEOUT_SEC` | `300` | Timeout de `terraform apply` em segundos (Phase 2c+) |
| `INFRA_TERRAFORM_ROOT` | (none) | cwd default p/ terraform; pode ser sobrescrito por chamada via `path` |
| `INFRA_TERRAFORM_BIN` | `terraform` | Caminho do binário |
| `INFRA_CHECKOV_BIN` | `checkov` | idem |
| `INFRA_INFRACOST_BIN` | `infracost` | idem |
| `INFRA_PLAN_TIMEOUT` | `120` | s |
| `INFRA_VALIDATE_TIMEOUT` | `30` | s |
| `INFRA_SCAN_TIMEOUT` | `180` | s |
| `INFRA_COST_TIMEOUT` | `60` | s |
| `INFRA_OUTPUT_MAX_CHARS` | `16000` | Truncamento defensivo do output |
| `INFRA_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `INFRA_LOG_FORMAT` | `json` | json/text — sempre stderr |

`.env.example` documenta todas.

## O que NÃO faz (e por quê)

| Operação | Status | Razão |
|---|---|---|
| `terraform apply` | fora do escopo Phase 1 | Mutação em produção exige aprovação humana e auditoria forense (ver ADR-0001) |
| `terraform destroy` | fora permanente | Apenas runbook humano com `--target` específico |
| `terraform state rm/push` | fora permanente | Risco de corrupção de state irreversível |
| Lifecycle de VM (start/stop) | Phase 2 | Exige throttling, idempotência |
| `keyvault read` (valor de segredo) | Phase 2 com cuidado | Risco de leak via log/response |
| Modificação de NSG/firewall | Phase 3 | Mudança crítica em produção |

## Roadmap

### Phase 1 — fundação read-only (este release)

Tools acima. Foundation para o allocator. Tem valor standalone como ferramenta de auditoria/validação.

### Phase 2 — VM allocator

Próximo PR. Tools planejadas (em ADR-0001 §"Phase 2"):

- `request_vm(spec, duration_min, exclusive, priority, owner)` — devolve `VMLease`, `QueuedRequest` ou `DeniedRequest`. Agente **não** roda terraform direto; o servidor decide entre compartilhar VM existente ou provisionar (com plan + checkov + infracost rodando internamente como Phase 1 tools).
- `extend_lease(lease_id, additional_min)`, `release_lease(lease_id)`, `get_lease(lease_id)`, `list_my_leases(owner)`, `list_pool()`, `query_capacity(spec)`.

Hard stops automáticos: cost cap, concurrent lease cap, spec whitelist, lease max duration, auto-release por inatividade, network/IAM permanecem humanos.

Sub-phases incrementais (2a..2f) detalhados em ADR-0001.

### Outras pendências

- v0.2.x: `tfsec` ao lado de `checkov`, `terraform_init` em sandbox isolado.
- Read-only adicionais: `azure_vm_list`, `azure_network_describe` (via `az`) — úteis ao próprio allocator para introspecção de pool.
- `keyvault_list_metadata` (apenas IDs e versions, nunca valor) — Phase 3.

## Testes

```bash
pytest tests/ -v
```

Subprocess é mockado nos testes. Não invoca `terraform` real durante CI.

## Convivência com `ai-governance-mcp-server`

- Servidores **separados** por design.
- Agente registra **ambos** no cliente MCP — pode chamar tools de governança E de infra na mesma sessão.
- HARD STOPS dos dois lados se reforçam: `validate_agent_decision` (do ai-governance) é o gate final antes do humano aplicar; `policy_scan_checkov` e `cost_estimate_infracost` (deste server) alimentam o validator com sinais concretos.
