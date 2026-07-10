# audit-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** / inner Twin Token) de **auditoria e
compliance** do DevTeam. Python 3.12, agregado atrás do `platform-mcp-gateway` — nunca
exposto direto à internet (ingress só via gateway, INV-1).

Persiste auditorias/aprovações em **PostgreSQL** (`AuditStore`) e roda checkers
(lint, testes, docs, segurança, estrutura) sobre repositórios, aplicando as políticas
por ambiente em `src/policies/{dev,hml,prod}.yaml`.

## Tools (9)

| Tool | Scope | Descrição |
|---|---|---|
| `run_audit` | `audit:write` | Executa auditoria completa de um repo num ambiente |
| `get_audit_status` | `audit:read` | Status da auditoria mais recente de um serviço/ambiente |
| `list_audits` | `audit:read` | Lista auditorias com filtros |
| `get_audit_report` | `report:read` | Relatório consolidado de conformidade |
| `get_audit_gate_result` | `gate:read` | Resultado do gate `audit_compliance` (p/ pipeline-mcp) |
| `get_compliance_policy` | `policy:read` | Política de conformidade de um ambiente |
| `get_compliance_checklist` | `checklist:read` | Checklist dinâmico (preview, sem persistir) |
| `submit_audit_approval` | `approval:write` | Aprovação/rejeição manual de uma auditoria |
| `set_service_criticality` | `criticality:write` | Define a criticidade de um serviço |

Todas exigem inner Twin Token válido (`aud=mcp:audit-mcp`, `jti`); o `tenant_id` vem
sempre dos claims do token (SEC-035 / INV-3), nunca de argumento do cliente.

## Endpoints (sidecar HTTP, `:MCP_PORT` = 7100)

- `GET /v1/health` — liveness (sem token)
- `GET /mcp/tools/list` — catálogo governado (capability, required_scope, resource_type, data_domain)
- `POST /mcp/tools/call` — execução (inner token obrigatório)

## Configuração

Um único `.env` (STD-SEC-004), discriminado por `RUNTIME_ENV ∈ {local, cloud}`. Veja
[`.env.example`](./.env.example). A senha do DB nunca fica no código: vem de env ou, se
`VAULT_ADDR` estiver setado, do Vault (`load_secret`), com degradação graciosa. No boot,
`enforce_security_invariants()` faz fail-fast (docs desabilitado, audiência `mcp:`, e —
em cloud — JWKS do admin e senha do DB obrigatórios).

## Dev

```bash
pip install -e ".[dev]"
python -m ruff check . && python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Registro no gateway: veja [`gateway/README.md`](./gateway/README.md).
Refs.: `STD-MCP-001`, `STD-SEC-001/004/006`, `STD-OBS-001`.
