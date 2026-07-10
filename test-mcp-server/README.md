# test-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** / inner Twin Token) de **engenharia de
testes** do DevTeam. Python 3.12, agregado atrás do `platform-mcp-gateway` — nunca
exposto direto à internet (ingress só via gateway, INV-1).

Persiste planos, cenários, checklists e bugs em **PostgreSQL** (`TestStore`, psycopg2 +
connection pool), a partir de templates por categoria (rest_api, react_component,
auth_flow, db_migration, websocket, form_validation, ui_data_validation).

## Tools (12)

| Tool | Scope | Descrição |
|---|---|---|
| `create_test_plan` | `plan:write` | Cria um plano de testes para uma feature/endpoint |
| `get_test_plan` | `plan:read` | Retorna um plano com métricas de cobertura e findings |
| `list_test_plans` | `plan:read` | Lista planos, opcionalmente por status |
| `generate_scenarios` | `scenario:write` | Gera cenários por template para uma categoria |
| `add_scenario` | `scenario:write` | Adiciona um cenário customizado ao plano |
| `record_result` | `scenario:write` | Registra o resultado da execução de um cenário |
| `create_checklist` | `checklist:write` | Cria checklist (template ou itens customizados) |
| `run_checklist` | `checklist:write` | Inicia uma execução (run) de um checklist |
| `check_item` | `checklist:write` | Marca um item do checklist (passed/failed/na/blocked) |
| `add_bug` | `bug:write` | Registra um bug vinculado a um plano |
| `double_check` | `validation:read` | Verificação completa do plano (APROVADO/BLOQUEADO) |
| `get_validation_status` | `validation:read` | Cobertura %, pass rate %, findings e grade (A–F) |

Todas exigem inner Twin Token válido (`aud=mcp:test-mcp`, `jti`); o `tenant_id` vem
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
