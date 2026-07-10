# infra-mcp-server

Sidecar **MCP (kind=`mcp_http`, Model C)** de infraestrutura do ecossistema
`dataforalltech`. Agregado ao **MCP Gateway central** (`platform-mcp`) — os agentes
nunca falam com este server direto; o gateway roteia, e o sidecar re-verifica o
**inner Twin Token** (`aud=mcp:infra-mcp`) por defesa em profundidade.

- Namespace canônico: `infra-mcp` (audiência do inner token: `mcp:infra-mcp`).
- Transporte: stdio (MCP) + sidecar HTTP (`:MCP_PORT`, default `7100`).
- Persistência: **SQLite embarcado** (`AllocatorStore`) — leases e pool sobrevivem a
  restart. Sem backend Trinity/REST; as tools operam CLIs locais
  (`terraform`/`checkov`/`infracost`) e o allocator de VMs.

Contratos: `STD-MCP-001` (integração com o gateway), `STD-SEC-006` (token Model C /
inner token), `STD-SEC-001/004` (docs off, segredos fora do código), `STD-OBS-001`
(logging JSON estruturado).

## Tools (15)

### Terraform / policy / cost — read-only (6)

| Tool | CLI | O que faz |
|---|---|---|
| `terraform_validate` | `terraform validate -json` | Sintaxe + tipo |
| `terraform_fmt_check` | `terraform fmt -check -diff` | Estilo (não modifica) |
| `terraform_plan` | `terraform plan -out -detailed-exitcode` | Resumo + `.tfplan` binário |
| `terraform_show_plan` | `terraform show -json <plan>` | Plan estruturado |
| `policy_scan_checkov` | `checkov -d <path> -o json` | Findings + `hard_stop` em HIGH/CRITICAL |
| `cost_estimate_infracost` | `infracost diff --path <plan>` | Delta de custo + `hard_stop` por threshold |

Sem o binário no PATH (ou `INFRA_<TOOL>_BIN`), a tool retorna `error: binary_not_found`;
a sessão segue OK para as demais.

### VM allocator — read + write (9)

| Tool | O que faz |
|---|---|
| `request_vm(spec, duration_min, owner, exclusive=False, priority="low", purpose=None, human_approved=False)` | Aloca capacidade. Allocator decide: lease compartilhado, nova VM, fila ou denial. Retorna `AllocationDecision` (`outcome=LEASED\|QUEUED\|DENIED`). |
| `get_lease(lease_id)` | Estado atual + `connection_hint`. |
| `release_lease(lease_id, by=None)` | Idempotente; VM órfã é terminada (terraform destroy em background). |
| `extend_lease(lease_id, additional_min)` | Bump de expiry; cap 24h totais, máx 3 extensões. |
| `list_my_leases(owner, status=None)` | Leases do agente. |
| `list_pool()` | Snapshot administrativo (VMs + custo/hora total). |
| `query_capacity(spec, owner=None)` | Planejamento sem efeito colateral. |
| `get_lease_ssh_key(lease_id, owner)` | Chave privada Ed25519 PEM da VM. Requer lease ACTIVE + owner. Chave deletada no release. |
| `cancel_queued_request(request_id, by=None)` | Cancela request `WAITING` na fila. |

Hard stops do allocator: cost cap (`$5/h` no pool por default), máx 3 leases ativos por
owner, lease máx 24h/3 extensões, specs whitelist sem aprovação (`cpu-small/medium/large`)
e specs que exigem `human_approved=True` (`gpu-a100`, `high-mem`).

## Requisitos

- Python ≥ 3.12
- No PATH (ou via `INFRA_<TOOL>_BIN`): `terraform` ≥ 1.5, `checkov` ≥ 3.0,
  `infracost` ≥ 0.10 — necessários apenas para as tools correspondentes.

## Config (STD-SEC-004 — um único `.env`, gitignored)

Copie `.env.example` para `.env`. Env-vars canônicas do gateway são lidas **sem** o
prefixo `INFRA_` (via `validation_alias`); as demais mantêm o prefixo `INFRA_`.

| Var | Default | Função |
|---|---|---|
| `RUNTIME_ENV` | `local` | Discriminador de ambiente: `local` \| `cloud`. Em `cloud`, `URL_ADMIN_TWIN_JWKS` é obrigatório. |
| `MCP_TWIN_AUDIENCE` | `mcp:infra-mcp` | Audiência exata re-verificada no inner token. |
| `URL_ADMIN_TWIN_JWKS` | (vazio) | JWKS do `platform-admin` (emissor do twin token). |
| `MCP_PORT` | `7100` | Porta do sidecar HTTP. |
| `DOCS_ENABLED` | `false` | Swagger/OpenAPI NUNCA exposto (STD-SEC-001). |
| `MCP_SERVICE_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR — logs JSON em stderr. |
| `INFRA_DB_PATH` | `:memory:` | SQLite do allocator; `/data/allocator.db` para persistir. |
| `INFRA_LEASE_SECRET` | (vazio) | Fernet key (base64, 32 bytes) que cifra chaves SSH por VM. Vazio → chave efêmera por sessão. Resolvido via **Vault-fallback** (`VAULT_ADDR`) → env. |
| `INFRA_TF_MODULES_ROOT` | (none) | Raiz dos módulos terraform por cloud. None → `ImmediateProvisioner` (mock). |
| `INFRA_COST_CAP_USD_MONTH` | (none) | Cap mensal via `infracost diff`. None → sem verificação. |
| `INFRA_TF_BACKEND_TYPE` | `local` | `local` (state por VM) \| `s3` \| `azurerm` \| `gcs` (workspaces por VM). |
| `INFRA_PROVISION_TIMEOUT_SEC` | `300` | Timeout de `terraform apply`. |

Segredos são resolvidos por `src/config/secrets.load_secret`: se `VAULT_ADDR` estiver
setado tenta `platform_crypto.VaultSecretsClient` (import lazy); qualquer falha degrada
graciosamente para o `.env` — o boot **nunca** quebra por causa do Vault.

## Segurança (fail-fast no boot)

`Settings.enforce_security_invariants()` é chamado em `build_server()` e aborta o boot se:
`DOCS_ENABLED=true`, `MCP_TWIN_AUDIENCE` não for `mcp:<namespace>`, ou `RUNTIME_ENV=cloud`
sem `URL_ADMIN_TWIN_JWKS`. O `tenant_id` vem SEMPRE dos claims do inner token verificado,
nunca de argumento do cliente (SEC-035 / INV-3).

## Desenvolvimento

```bash
cd infra-mcp-server
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Subprocess e JWKS são mockados nos testes; o allocator usa SQLite `:memory:` — nenhum
I/O de rede ou `terraform` real no CI.

## Endpoints do sidecar HTTP

| Rota | Descrição |
|---|---|
| `GET /v1/health` | Liveness (sem token). |
| `GET /mcp/tools/list` | Catálogo governado (schema + `capability`/`required_scope`/`resource_type`/`data_domain` por tool). |
| `POST /mcp/tools/call` | Execução; inner token obrigatório (exceto `_EXEMPT_TOOLS`). |

## Convivência com `ai-governance-mcp-server`

Servidores separados por design: `policy_scan_checkov` e `cost_estimate_infracost`
alimentam o `validate_agent_decision` do ai-governance com sinais concretos antes do
gate humano.
