# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versionamento: SemVer.

## [Unreleased]

### Added — Phase 2h (Priority queue + preemption)

- **`queued_requests` SQLite table** (nova tabela em `AllocatorStore`):
  - Campos: `request_id`, `spec`, `duration_min`, `owner`, `purpose`, `exclusive`, `priority`, `human_approved`, `created_at`, `status` (`WAITING | FULFILLED | CANCELLED`).
  - Index em `(status, priority, created_at)` para ordenação eficiente.
  - Migração idempotente via `CREATE TABLE IF NOT EXISTS` no `_init_schema()`.

- **`AllocationDecision`** — novo campo:
  - `request_id: str | None` — presente apenas quando `outcome=QUEUED`. Permite rastrear/cancelar a requisição na fila.

- **Preemption (priority='high')** — em `request_vm()`, quando cost cap é atingido:
  - `_find_preemptable_vms_inside_lock(spec_cost)`: encontra VMs READY onde **todos** os leases têm `priority='low'`. Seleção greedy por custo decrescente até cobrir o déficit.
  - `_preempt_vms_inside_lock(vms, reason)`: força `RELEASED` em todos os leases + `TERMINATED` nas VMs + deleta SSH keys. Chamado dentro de transação (`BEGIN/COMMIT`).
  - Destroy das VMs preemptadas agendado via `_schedule_destroy()` (seguro dentro do lock).
  - Se preemption cobre o déficit → provisiona nova VM normalmente (sem enfileirar).
  - Se preemption não cobre (ou priority ≠ 'high') → salva na fila via `_save_queued_request()`.

- **Processamento da fila** — `_try_fulfill_queued_inside_lock()` chamado em:
  - `release_lease()` (capacity freed quando VM é terminada).
  - `_on_vm_ready()` (VM recém-READY pode atender requests via share sem custo adicional).
  - `_on_vm_failed()` (VM falhou → orçamento liberado).
  - Lógica: para cada WAITING em ordem `(high → medium → low, FIFO)`:
    1. Verifica owner concurrent cap.
    2. Tenta share em VM READY existente (sem custo adicional).
    3. Se não → verifica cost cap para nova VM. Se OK → provisiona. Se não → pula.
  - Retorna lista de `(VMInfo, public_key, VMRequest)` para provisionar **fora do lock**.

- **`cancel_queued_request(request_id, by=None)`** — 15ª tool MCP:
  - Store method: cancela request WAITING → `CANCELLED`. Levanta `AllocatorStoreError` se não existe ou não está `WAITING`.
  - Tool function em `allocator_tool.py`: `cancel_queued_request(store, request_id, by)`.
  - Schema em `_TOOL_SCHEMAS`. Dispatch em `_dispatch()`. Export em `__init__.py`.

- **19 novos testes** em `tests/test_queue.py` (195 total, 0 falhas):
  - `TestQueueBasics` (4): queuing, request_id, posição, estimated_wait_min.
  - `TestCancelQueuedRequest` (3): success, not found, already cancelled.
  - `TestPreemption` (5): preemption high→low, sem preemption para medium/low, VM com lease medium não preemptável, múltiplas VMs greedy.
  - `TestQueueFulfillment` (5): fulfilled on release, not fulfilled se ainda over cap, share via VM READY, cancelled not fulfilled, on_vm_failed trigger.
  - `TestQueueOrder` (2): high antes de low na fila, apenas 1 VM provisionada quando cap permite 1.

### Changed — Phase 2h

- `request_vm()` refatorado: cost cap retorna `AllocationDecision` com `request_id` (antes: sem request_id).
- `release_lease()`, `_on_vm_ready()`, `_on_vm_failed()` — provisão de VMs da fila feita fora do lock via lista de `to_provision`.
- `test_server_dispatch.py::test_all_tools_registered` atualizado para incluir `cancel_queued_request`.

---

### Added — Phase 2g (Multi-spec catalog completo + infracost cost cap)

- **6 novos módulos terraform** (gpu-a100 e high-mem para 3 clouds):
  - `aws/gpu-a100`: EC2 p3.2xlarge (8 vCPU, 61 GiB RAM, 1x NVIDIA Tesla V100 16 GB, ~$3.06/h).
  - `aws/high-mem`: EC2 r5.2xlarge (8 vCPU, 64 GiB RAM, ~$0.50/h).
  - `azure/gpu-a100`: Standard_NC6s_v3 (6 vCPU, 112 GiB RAM, 1x Tesla V100 16 GB).
  - `azure/high-mem`: Standard_E8s_v3 (8 vCPU, 64 GiB RAM).
  - `gcp/gpu-a100`: a2-highgpu-1g (12 vCPU, 85 GiB RAM, 1x NVIDIA A100 40 GB, ~$3.67/h).
  - `gcp/high-mem`: n2-highmem-8 (8 vCPU, 64 GiB RAM, ~$0.67/h).
  - Todos usam `ssh_public_key` (Ed25519 por VM, Phase 2f). GCP gpu-a100 inclui `guest_accelerator` + `on_host_maintenance = "TERMINATE"`.

- **`TerraformProvisioner` — fluxo plan → infracost → apply** (Phase 2g):
  - `__init__` recebe `infracost_bin: str = "infracost"` e `cost_cap_usd_month: float | None = None`.
  - `_run()` refatorado: `terraform plan -out=<vm_id>.tfplan` → `_check_cost()` → `terraform apply <vm_id>.tfplan` (sem `-auto-approve`). Plan file limpo em `finally`.
  - `_check_cost()`: roda `infracost diff --path <planfile> --format json`, extrai `totalMonthlyCost`. Se `monthly_cost > cap` → `on_failed` (bloqueante). Se infracost não encontrado / timeout / nonzero / parse error → warning log + continua (non-blocking).
  - Plan files (`*.tfplan`) em module dir, gitignored, limpos após apply.

- **`Settings`** — novo campo:
  - `INFRA_COST_CAP_USD_MONTH` (`float | None`) — cap mensal em USD por provisão via infracost.

- **10 novos testes** (176 total, 0 falhas):
  - `TestTerraformProvisionerMocked` — 3 novos: `test_plan_step_called_before_apply`, `test_plan_failure_calls_on_failed`, `test_plan_file_cleaned_up_after_success`.
  - `TestTerraformProvisionerInfracost` — 7 novos: no cap/skip, cap OK, cap excedido bloqueia apply, binary not found/timeout/parse error/nonzero exit são non-blocking.

### Changed — Phase 2g

- `TerraformProvisioner._run()` usa `plan → infracost → apply <planfile>` (antes: `apply -auto-approve`).
  Existing behavior preservado: fluxo destroy mantém `-auto-approve`.
- Tests `test_apply_failure_calls_on_failed` e `test_missing_output_key_calls_on_failed` atualizados para side_effect baseada em `cmd[1]` (plan vs apply).

---

### Added — Phase 2f (SSH key per-VM + backend remoto)

- **`cryptography>=42.0.0`** adicionada como dependência (Ed25519 + Fernet).

- **`src/knowledge/ssh_key.py`** (novo módulo):
  - `generate_keypair() -> (private_pem, public_openssh)` — par Ed25519.
  - `generate_fernet_key() -> bytes` — Fernet key aleatória.
  - `encrypt_private_key(pem, fernet_key) -> bytes` — AES-128-CBC + HMAC-SHA256.
  - `decrypt_private_key(encrypted, fernet_key) -> str` — decifragem autenticada.

- **`AllocatorStore`** — geração e armazenamento de keypair SSH por VM:
  - Nova tabela SQLite **`vm_keys(vm_id, encrypted_private_key, public_key, created_at)`**.
  - `_start_provisioning()` gera keypair → insere em `vm_keys` → retorna `(VMInfo, public_openssh)`.
  - `request_vm()` passa `extra_tf_vars={"ssh_public_key": pubkey}` ao provisioner.
  - **`get_lease_ssh_key(lease_id, owner) -> str`** (novo): retorna chave privada PEM. Requer
    lease `ACTIVE` + `owner` correto. Chave deletada de `vm_keys` ao terminar VM.
  - Cleanup de `vm_keys`: `_detach_lease_from_vm_tx` (último lease), `_on_vm_failed`, `_gc_expired`.
  - Novo parâmetro `lease_secret: str | None` — Fernet key para cifragem. Auto-gerado por sessão se None.

- **`Provisioner` Protocol + implementações** — `extra_tf_vars: dict[str, str] | None = None` em `provision()`:
  - `ImmediateProvisioner`: aceita e ignora `extra_tf_vars`.
  - `TerraformProvisioner`: converte `extra_tf_vars` para env `TF_VAR_<key>=<val>` no subprocess.

- **Backend remoto** (S3/AzureRM/GCS) via `INFRA_TF_BACKEND_TYPE`:
  - `TerraformProvisioner` aceita `backend_type` e `backend_config: dict[str, str]`.
  - `_ensure_init_remote()`: escreve `_backend_override.tf` (gitignored) + `terraform init -reconfigure -backend-config=...`. Lock por spec dir evita concorrência.
  - `_workspace_create_or_select()`: `terraform workspace new <vm_id>` (ou select se existente).
  - `_run_destroy_remote()`: `workspace select <vm_id>` → `destroy` → `workspace delete <vm_id>`.
  - Backend local (`backend_type="local"`) mantém comportamento Phase 2d/2e (`-state` flags).

- **Módulos AWS atualizados** (3 módulos: cpu-small, cpu-medium, cpu-large):
  - Remove `var.key_name` (EC2 Key Pair pré-existente).
  - Adiciona `var.ssh_public_key` + `resource "aws_key_pair" "vm"` por VM.
  - `aws_instance.vm.key_name = aws_key_pair.vm.key_name`.

- **Nova tool MCP** `get_lease_ssh_key(lease_id, owner)` (14ª tool):
  - Retorna `{private_key_pem, key_type: "ed25519", warning}`.
  - Erros tipados: `lease_not_found`, `allocator_error`, `validation_error`.

- **Settings** — novos campos (prefixo `INFRA_`):
  - `INFRA_LEASE_SECRET` — Fernet key para cifrar chaves SSH entre restarts.
  - `INFRA_TF_BACKEND_TYPE` — tipo de backend (`local`, `s3`, `azurerm`, `gcs`).
  - `INFRA_TF_BACKEND_CONFIG_JSON` — JSON com config backend-específica.

- **23 novos testes** em `tests/test_ssh_key.py` (166 total, 0 falhas):
  - `TestSSHKeyModule` — 5 testes (keypair Ed25519, round-trip Fernet, tamanho key).
  - `TestAllocatorSSHKeys` — 8 testes (vm_keys criado, get retorna PEM, erros de acesso, cleanup em 3 pontos).
  - `TestGetLeaseSSHKeyTool` — 5 testes (PEM retornado, erros por owner/lease_id/empty).
  - `TestTerraformProvisionerRemoteBackend` — 3 testes (extra_tf_vars→env, backend_override.tf, workspace skip).

### Changed — Phase 2f

- `AllocatorStore._start_provisioning()` retorna `tuple[VMInfo, str]` (antes: só `VMInfo`).
- `test_server_dispatch.py::test_all_tools_registered` atualizado para incluir `get_lease_ssh_key`.
- Todos os mock provisioners em testes (`AsyncMockProvisioner`, `RecordingProvisioner`, provisioners inline) receberam `extra_tf_vars=None` em `provision()`.

### Added — Phase 2e (Destroy automático + cpu-large)

- **`TerraformProvisioner.destroy()`** (novo): destrói VM via `terraform destroy` em background thread.
  - Verifica se `states/<vm_id>.tfstate` existe; se não → `on_done()` imediato (idempotente).
  - Passa `-state=<statefile> -state-out=<statefile>` no destroy.
  - Remove state file após destroy bem-sucedido.
  - Em falha: chama `on_failed(err)` com mensagem incluindo `"manual_destroy_required"` no log.

- **`ImmediateProvisioner.destroy()`** (novo): no-op (chama `on_done()` imediatamente).

- **`Provisioner` Protocol** atualizado: `destroy(spec, vm_id, modules_root, timeout_sec, on_done, on_failed)` adicionado ao contrato.

- **`OnDone = Callable[[], None]`** — novo tipo exportado por `src/knowledge/provisioner.py`.

- **`AllocatorStore._schedule_destroy(vm_id, spec)`** (novo): chama `provisioner.destroy()` registrando resultado nos logs. Três pontos de disparo:
  - **`release_lease`**: quando o último lease de uma VM é liberado → VM TERMINATED → destroy.
  - **`_on_vm_failed`**: quando provisão falha → VM TERMINATED → destroy (idempotente se nada foi criado).
  - **`_gc_expired`**: quando leases expiram e VM fica órfã → VM TERMINATED → destroy.

- **`_detach_lease_from_vm_tx`** retorna `bool` (foi a VM terminada?) — usado em `release_lease`.

- **Módulos terraform cpu-large** (3 novos):
  - `aws/cpu-large/`: EC2 **m5.2xlarge** (8 vCPU, 32 GiB), disk 50 GiB gp3.
  - `azure/cpu-large/`: **Standard_D8s_v3** (8 vCPU, 32 GiB), disk 80 GiB Premium_LRS.
  - `gcp/cpu-large/`: **e2-standard-8** (8 vCPU, 32 GiB), disk 50 GiB pd-ssd.

- **+11 testes** em `tests/test_provisioner.py`:
  - `TestImmediateProvisionerDestroy` (2): on_done síncrono, on_failed nunca chamado.
  - `TestTerraformProvisionerDestroyFallbacks` (3): no-op sem modules_root, sem spec dir, sem state file.
  - `TestTerraformProvisionerDestroyMocked` (2): happy path (state file removido), falha (state preservado).
  - `TestAllocatorDestroyIntegration` (4): destroy em release_lease (último lease), VM ainda shared (sem destroy), falha de provisão, GC de leases expirados.

- **`AsyncMockProvisioner`** (em tests) atualizado com `destroy()` — evita warning de thread sem `destroy`.

### Limites conhecidos (Phase 2e)

- **Backend remoto** (S3/AzureRM/GCS): ainda local. State file em `<module_dir>/states/<vm_id>.tfstate`. Phase 2f (ou configuração manual) migra para backend remoto.
- **`gpu-a100`, `high-mem`** sem módulos terraform ainda — aprovação humana enforced no allocator nível de policy.

---

### Added — Phase 2d (Módulos terraform multi-cloud reais)

- **`terraform-modules/aws/cpu-small/`** e **`terraform-modules/aws/cpu-medium/`**: EC2 t3.medium / t3.xlarge.
  - AMI: Ubuntu 20.04 LTS via `data "aws_ami"` (Canonical owner `099720109477`, filtro `ubuntu-focal-20.04-amd64`).
  - Security Group dedicado por VM (`infra-alloc-<vm_id>`): SSH restrito a `TF_VAR_ssh_source_cidr` (default `10.0.0.0/8`).
  - EBS gp3, 20 GiB (small) / 30 GiB (medium), criptografado, `delete_on_termination = true`.
  - IMDSv2 obrigatório (`http_tokens = "required"`).
  - Variáveis obrigatórias: `TF_VAR_subnet_id`, `TF_VAR_vpc_id`, `TF_VAR_key_name`.
  - Output `vm_ssh_endpoint`: `coalesce(public_ip, private_ip):22`.
  - Ambiente alvo: DEV / HML.

- **`terraform-modules/azure/cpu-small/`** e **`terraform-modules/azure/cpu-medium/`**: Standard_B2s / Standard_D4s_v3.
  - Imagem: Ubuntu 20.04 LTS Gen2 (`0001-com-ubuntu-server-focal` / `20_04-lts-gen2`).
  - Public IP estático (SKU Standard) + NIC em subnet pré-aprovada.
  - `disable_password_authentication = true` — apenas SSH key.
  - OS disk Premium_LRS, 30 GiB (small) / 50 GiB (medium).
  - Variáveis obrigatórias: `TF_VAR_resource_group`, `TF_VAR_subnet_id`, `TF_VAR_admin_ssh_public_key`.
  - Output `vm_ssh_endpoint`: `azurerm_public_ip.ip_address:22`.
  - Ambiente alvo: PROD.

- **`terraform-modules/gcp/cpu-small/`** e **`terraform-modules/gcp/cpu-medium/`**: e2-medium / e2-standard-4.
  - Imagem: Ubuntu 20.04 LTS via `data "google_compute_image"` (family `ubuntu-2004-lts`, project `ubuntu-os-cloud`).
  - Firewall rule tag-based por VM (`alloc-ssh-<8chars>`): SSH restrito ao CIDR configurado.
  - `block-project-ssh-keys = "true"` — SSH key restrita à instância.
  - pd-ssd, 20 GiB (small) / 30 GiB (medium), `auto_delete = true`.
  - Variáveis obrigatórias: `TF_VAR_project`, `TF_VAR_network`, `TF_VAR_subnetwork`, `TF_VAR_ssh_public_key`.
  - Output `vm_ssh_endpoint`: `nat_ip:22` (IP externo via access_config).
  - Ambiente alvo: testes pontuais na GCP.

- **`src/knowledge/provisioner.py`** — state isolation (Phase 2d fix):
  - `TerraformProvisioner._run` cria `<module_dir>/states/<vm_id>.tfstate` para cada VM.
  - Passa `-state=<statefile> -state-out=<statefile>` no `apply` e `-state=<statefile>` no `output`.
  - Provisões concorrentes do mesmo spec não conflitam mais em `terraform.tfstate`.

- **`.gitignore` de todos os módulos** inclui `states/` para não commitar state de VMs reais.

### Configuração por ambiente (Phase 2d)

| Ambiente | `INFRA_TF_MODULES_ROOT` | Variáveis obrigatórias adicionais |
|---|---|---|
| DEV/HML (AWS) | `terraform-modules/aws` | `TF_VAR_subnet_id`, `TF_VAR_vpc_id`, `TF_VAR_key_name` + credenciais AWS |
| PROD (Azure) | `terraform-modules/azure` | `TF_VAR_resource_group`, `TF_VAR_subnet_id`, `TF_VAR_admin_ssh_public_key` + ARM_* |
| Testes (GCP) | `terraform-modules/gcp` | `TF_VAR_project`, `TF_VAR_network`, `TF_VAR_subnetwork`, `TF_VAR_ssh_public_key` + GOOGLE_* |

### Limites conhecidos (Phase 2d)

- **Sem terraform destroy automático**: `release_lease` → VM marcada `TERMINATED` no allocator, mas recurso cloud não é destruído. Operador deve rodar `terraform destroy -state=states/<vm_id>.tfstate` no diretório do módulo. Phase 2e adiciona `TerraformProvisioner.destroy()`.
- **Backend local**: state file em `<module_dir>/states/<vm_id>.tfstate`. Não compartilhável entre instâncias do allocator. Phase 2e migra para backend remoto (S3/AzureRM/GCS).
- **`terraform init` compartilhado**: `.terraform/` do módulo é compartilhado entre VMs do mesmo spec. Idempotente por design, mas concurrent inits podem competir na primeira vez.
- **`cpu-large`, `high-mem`, `gpu-a100`**: sem módulos Phase 2d. Phase 2e/2f adiciona, com aprovação humana enforced no allocator.

---

### Added — Phase 2c (Provisioner injetável + terraform real)

- **`src/knowledge/provisioner.py`** (novo): `Provisioner` (Protocol), `ImmediateProvisioner`, `TerraformProvisioner`.
  - `ImmediateProvisioner`: `on_ready` chamado de forma **síncrona** — sem thread, sem terraform. Comportamento idêntico ao Phase 2b. Default quando `INFRA_TF_MODULES_ROOT` não configurado.
  - `TerraformProvisioner`: `provision()` spawna background thread que executa `terraform init/apply/output`, extrai `vm_ssh_endpoint` do output JSON e chama `on_ready(hint)` ou `on_failed(err)`.

- **`AllocatorStore`** agora aceita `provisioner`, `tf_modules_root` e `provision_timeout_sec` no `__init__`.
  - VM criada como `PROVISIONING`, lease como `PENDING` para VMs novas.
  - `_on_vm_ready(vm_id, hint)` → VM=READY, leases PENDING→ACTIVE, `exclusive_locked_by` setado se lease exclusivo.
  - `_on_vm_failed(vm_id, err)` → VM=TERMINATED, leases PENDING→EXPIRED.
  - Para VMs compartilhadas (já READY): lease criado diretamente como ACTIVE (sem espera).
  - `connection_hint` na tabela `vms` — migration idempotente via `ALTER TABLE ... ADD COLUMN`.
  - Provisioner chamado **fora do RLock** para não bloquear novas requests enquanto terraform roda.

- **`Settings`**: `INFRA_TF_MODULES_ROOT` (Path|None) e `INFRA_PROVISION_TIMEOUT_SEC` (int, default 300).

- **`mcp_server.py`**: instancia `TerraformProvisioner` se `tf_modules_root` configurado, senão `ImmediateProvisioner`. Loga `provisioner` no startup.

- **`terraform-modules/cpu-small/`** (novo): módulo stub — `null_resource` + output `vm_ssh_endpoint="stub-<vm_id>.local:22"` e `variables.tf` com `vm_id`, `spec`, `location`, `resource_group`. Funciona com `terraform init/apply/output` localmente sem Azure.

- **`tests/test_provisioner.py`** (novo): 13 testes.
  - `TestImmediateProvisioner`: 3 testes (síncrono, on_failed nunca chamado, hint contém vm_id).
  - `TestTerraformProvisionerFallbacks`: 2 testes (modules_root=None, spec dir ausente).
  - `TestTerraformProvisionerMocked`: 3 testes (happy path, apply failure, missing output key) — subprocess mockado.
  - `TestAllocatorWithAsyncProvisioner`: 5 testes (PENDING→ACTIVE, pool READY, falha→EXPIRED, exclusive lock, ImmediateProvisioner ainda ACTIVE imediato).

### Limites conhecidos (Phase 2c)

- **Módulo stub** (null_resource): não provisiona Azure real. Phase 2d adiciona módulo `azurerm_linux_virtual_machine` em subnet pré-aprovada.
- **`terraform init` pode ser lento** (download providers) — skip automático se `.terraform/` já existe. Phase 2d pré-inicializa módulos no Docker image.
- **connection_hint ainda simulada** para ImmediateProvisioner (`mock://vm_id:22`). Com TerraformProvisioner + módulo Azure: IP real da VM.
- **Sem heartbeat do agente** → Phase 2f.

---

### Added — Phase 2b (SQLite persistence)

- **`AllocatorStore` agora persiste em SQLite** (`src/knowledge/allocator_store.py`):
  - Schema auto-criado no `__init__` (`CREATE TABLE IF NOT EXISTS vms/leases`).
  - `db_path=":memory:"` (default) → banco em memória — testes isolados e rápidos.
  - `db_path="/path/file.db"` → persiste em disco. VMs e leases sobrevivem a server restart.
  - `isolation_level=None` (autocommit) + `BEGIN/COMMIT` explícito para operações multi-step.
  - `PRAGMA journal_mode=WAL` + `PRAGMA foreign_keys=ON`.
  - `close()` exposto para testes com `tmp_path`.
  - Datetimes como ISO-8601 UTC strings; booleans como INTEGER.
  - `_find_compatible_vm` via SQL puro (sem reconstructar todos os VMInfo em memória).
  - GC de leases expirados em SQL batch + terminação de VMs órfãs em único transaction.

- **`INFRA_DB_PATH`** — nova variável de ambiente em `Settings`; default `allocator.db` (cwd do processo). `:memory:` para testes.

- **`mcp_server.py`** instancia `AllocatorStore(db_path=settings.db_path, ...)` e loga `db_path` no startup.

- **10 testes novos** em `tests/test_allocator_persistence.py`:
  `test_lease_survives_restart`, `test_pool_survives_restart`, `test_release_persists_after_restart`,
  `test_extension_count_persists`, `test_multiple_leases_per_owner_survive_restart`,
  `test_exclusive_lock_persists`, `test_sharing_works_after_restart`,
  `test_cost_cap_enforced_across_restart`, `test_schema_is_idempotent`, `test_memory_store_isolation`.

- **1 teste adaptado** (`test_expired_lease_marked_on_next_operation`) — usa `store._con.execute()` para manipular `expires_at` diretamente no SQLite em vez de `store._leases`.

### Limites conhecidos (Phase 2b)

- **Provisão ainda simulada**. `vm_id` é UUID; `connection_hint` é mock URL. Phase 2c integra terraform.
- **Single-process**. `RLock` Python suficiente; multi-host exige Phase 2c+ com lock de arquivo ou banco externo.
- **Sem migrations automáticas**. Schema muda entre fases → mantenedor apaga o `.db` ao fazer upgrade (aceitável Phase 2b; Phase 2c adiciona `alembic`/`migrate`).
- **Network/IAM permanece humano**.

### Hard stops do allocator (sem mudança)

Idênticos ao Phase 2a — ver tabela no CHANGELOG do Phase 2a abaixo.

---

### Added — Phase 2a (VM allocator in-memory)

- **7 tools MCP de alocação** sobre o `AllocatorStore`:
  - `request_vm(spec, duration_min, owner, exclusive=False, priority="low", purpose=None, human_approved=False)` — agente solicita capacidade. Servidor decide entre lease compartilhado, provisão nova (Phase 2a: simulada), fila ou denial.
  - `get_lease(lease_id)` — estado atual + connection_hint.
  - `release_lease(lease_id, by=None)` — idempotente; quando última lease de uma VM é liberada, VM é terminada.
  - `extend_lease(lease_id, additional_min)` — bump expiry. Cap absoluto: 24h totais e máx 3 extensões.
  - `list_my_leases(owner, status=None)` — leases do agente.
  - `list_pool()` — snapshot administrativo (VMs + active_lease_count + custo/hora).
  - `query_capacity(spec, owner=None)` — planejamento sem efeito; retorna `can_satisfy_now`, `by_existing_vm`, `would_provision`, `blocked_by` quando recusado.
- **Domain model** (`src/models/allocator.py`): `VMSpec` (catálogo fechado: cpu-small/medium/large + high-mem + gpu-a100), `VMRequest`, `VMLease` (status PENDING/ACTIVE/RELEASED/EXPIRED), `VMInfo` (status PROVISIONING/READY/DRAINING/TERMINATED), `VMPoolSnapshot`, `AllocationDecision` (LEASED/QUEUED/DENIED), `CapacityResponse`. Whitelist `HUMAN_APPROVAL_REQUIRED_SPECS = {"gpu-a100", "high-mem"}`. Custo por hora `SPEC_COST_USD_PER_HOUR` em USD para enforcement de cost cap.
- **AllocatorStore** (`src/knowledge/allocator_store.py`): in-memory thread-safe (RLock), strategy `try-share-first → provision-if-budget → queue-or-deny`. Hard stops: cost cap default $5/h, max 3 leases ativos por owner, lease cap 24h, max 3 extensões por lease, spec whitelist sem aprovação `{cpu-small, cpu-medium, cpu-large}`. GC automático de leases expirados em toda operação.
- **60 testes novos**: `tests/test_allocator_store.py` (lógica do store: strategy, hard stops, lifecycle, GC, sharing) + `tests/test_allocator_tool.py` (interface dos 7 tools) + extensões em `tests/test_server_dispatch.py` (registro + dispatch das tools 2a).
- **mcp_server.py**: 7 schemas JSON novos, dispatch atualizado para receber `AllocatorStore` instanciado uma vez no `build_server` (lifetime do processo). Total de tools registradas: 13 (6 Phase 1 + 7 Phase 2a).
- **ADR-0001 atualizado** com seção "Status Phase 2a (delivered)" anotando o que foi entregue, limites conhecidos (in-memory; restart limpa estado), e o que vem nas próximas sub-phases.

### Limites conhecidos (Phase 2a)

- **State em memória apenas**. Restart do servidor → leases perdidos, VMs simuladas perdidas. Phase 2b adiciona SQLite.
- **Provisão é simulada**. `vm_id` é um UUID; `connection_hint` é mock URL. Phase 2c integra com terraform module pré-aprovado.
- **Sem fila persistente**. `outcome=QUEUED` é resposta ao agente "tente novamente quando algum lease liberar" — o servidor não memoriza a fila.
- **Single-process apenas**. Concorrência via `RLock`; multi-process ou multi-host exigirá Phase 2c+ com store compartilhado.
- **Network/IAM permanece humano**. Allocator não cria VNet, NSG, role assignments, KeyVault entries. Provisão futura usa recursos pré-existentes.

### Hard stops do allocator (referência rápida)

| Caso | Comportamento |
|---|---|
| spec gpu-a100 / high-mem sem `human_approved=True` | DENIED (`approval_required`) |
| spec fora da whitelist sem aprovação | DENIED |
| `duration_min` > 24h | DENIED |
| owner já tem 3 leases ativos | DENIED |
| Pool atingiu cost cap ($5/h default) | QUEUED com hint de retry |
| Tentar estender lease em status ≠ PENDING/ACTIVE | erro tipado |
| Extensão excederia 24h totais | erro tipado |
| Mais de 3 extensões | erro tipado |

## [0.1.0] - Phase 1 (read-only foundation)

### Added

- 6 tools wrappers sobre CLIs (terraform validate/fmt/plan/show, checkov, infracost).
- Subprocess runner centralizado com timeout, truncamento, redação de secrets.
- Settings via pydantic-settings com prefixo `INFRA_`.
- ADR-0001 documenta escolha de servidor separado + Phase 1/Phase 2 split.
- 49 testes com subprocess mockado.
