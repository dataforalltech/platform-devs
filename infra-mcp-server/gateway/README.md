# Registro do infra-mcp no MCP Gateway (STD-MCP-001)

Artefatos de **registro declarativo pull-based** do sidecar `mcp_http` deste serviço
no `platform-mcp-gateway`. O sidecar **nunca** se auto-registra (CI-3) — o gateway lê
o registro no boot/refresh.

| Arquivo | Quando usar |
|---|---|
| [`gateway-mapping.sql`](./gateway-mapping.sql) | **Produção** (`REGISTRY_SOURCE=db`): 1 linha idempotente em `ADMIN_DATAFORALL.GATEWAY_MAPPING`. |
| [`twin-gateway-services.entry.json`](./twin-gateway-services.entry.json) | **Local/CI** (`REGISTRY_SOURCE=env`): entrada no array JSON de `TWIN_GATEWAY_SERVICES` (minifique numa linha). |

## Invariante nº 1 — audiência (a falha de integração mais comum: 401)

O gateway deriva mecanicamente:

```
name_microservice = "platform-infra-mcp"
  → namespace = removeprefix("platform-") = "infra-mcp"
  → inner-token audience = "mcp:infra-mcp"
      DEVE == MCP_TWIN_AUDIENCE do sidecar (src/config/settings.py)
```

`MCP_TWIN_AUDIENCE=mcp:infra-mcp` e `name_microservice=platform-infra-mcp`
já estão consistentes. Trave isso no CI com `ci-assert-audience.py` (STD-CICD-001).

## Contrato (resumo)

- `kind=mcp_http`, `call_style=mcp` → envelope `{params:{name,arguments,_meta:{twin_token}}}`.
- `mcp_url=http://platform-infra-mcp:7100` (DNS do container = name_microservice).
- `health_path=/v1/health` (sem token), `tools_list_path=/mcp/tools/list`, `tools_call_path=/mcp/tools/call`.
- `exemptTools=[]` — infra-mcp não expõe tool tokenless; toda execução exige inner token válido (`mcp:infra-mcp`, `jti`).
- `excludeTools=[]` — `get_lease_ssh_key` expõe chave privada Ed25519; a exposição é governada por `required_scope=infra-mcp:secret:write` (least-privilege). Se for necessário bloqueá-la no front-door, adicione-a a `_EXCLUDE_TOOLS`/`excludeTools`.

## Tools publicadas (15)

`infra:read` (plan/scan/validação/custo + leituras do allocator):
`terraform_validate`, `terraform_fmt_check`, `terraform_plan`, `terraform_show_plan`,
`policy_scan_checkov`, `cost_estimate_infracost`, `get_lease`, `list_my_leases`,
`list_pool`, `query_capacity`.

`infra:write` (mutação de infra / allocator / segredo):
`request_vm`, `release_lease`, `extend_lease`, `cancel_queued_request`, `get_lease_ssh_key`.

Ref.: `docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md`,
`docs/standards/STD-SEC-006-token-model-c-inner-token.md`,
`docs/it/IT-006-registrar-servico-no-mcp-gateway.md` (no platform-service-template).
