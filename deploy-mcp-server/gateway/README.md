# Registro do deploy-mcp no MCP Gateway (STD-MCP-001)

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
name_microservice = "platform-deploy-mcp"
  → namespace = removeprefix("platform-") = "deploy-mcp"
  → inner-token audience = "mcp:deploy-mcp"
      DEVE == MCP_TWIN_AUDIENCE do sidecar (src/config/settings.py)
```

`MCP_TWIN_AUDIENCE=mcp:deploy-mcp` e `name_microservice=platform-deploy-mcp`
já estão consistentes. Trave isso no CI com `ci-assert-audience.py` (STD-CICD-001).

## Contrato (resumo)

- `kind=mcp_http`, `call_style=mcp` → envelope `{params:{name,arguments,_meta:{twin_token}}}`.
- `mcp_url=http://platform-deploy-mcp:7100` (DNS do container = name_microservice).
- `health_path=/v1/health` (sem token), `tools_list_path=/mcp/tools/list`, `tools_call_path=/mcp/tools/call`.
- `exemptTools=[]` — deploy-mcp não expõe tool tokenless (o liveness é o endpoint
  `/v1/health`); execução de TODAS as tools exige inner token válido (`mcp:deploy-mcp`, `jti`).
- `excludeTools=[]` — nenhuma tool retorna segredo (denylist fail-safe vazia).

Cada tool declara no `/mcp/tools/list` os 4 campos de policy que o gateway lê
(sem derivar por nome): `capability` (`deploy-mcp.<tool>`), `required_scope`
(`deploy-mcp:<tipo>:<verbo>`), `resource_type` e `data_domain`.

Ref.: `docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md`,
`docs/standards/STD-SEC-006-token-model-c-inner-token.md`,
`docs/it/IT-006-registrar-servico-no-mcp-gateway.md` (no platform-service-template).
