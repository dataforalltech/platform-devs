# frontend-mcp-server

Sidecar **MCP** (`kind=mcp_http`, **Model C** — inner Twin Token) da persona
**frontend**. Serviço Python **compute-only**: gera artefatos de frontend/UI a
partir dos inputs, sem backend REST/Trinity a chamar.

Registrado no MCP Gateway central (`platform-mcp-gateway`) sob o namespace
`frontend-mcp` (audiência `mcp:frontend-mcp`). O ingress de produção é **sempre**
via gateway; o sidecar HTTP escuta em `:7100` apenas dentro da rede do gateway.

## Tools

| Tool | Scope | Descrição |
|------|-------|-----------|
| `status` | `frontend-mcp:status:read` | Status do servidor (nome, versão, nº de tools). Exempt (sem token). |
| `generate_react_component` | `frontend-mcp:component:write` | Scaffold de componente React (nome + variante). |
| `generate_nextjs_page` | `frontend-mcp:page:write` | Página Next.js (App Router) a partir da rota. |
| `generate_storybook_story` | `frontend-mcp:story:write` | Story de Storybook (CSF 3.0) do componente. |
| `generate_form_with_validation` | `frontend-mcp:form:write` | Formulário com React Hook Form + validação Zod. |

## Endpoints (sidecar HTTP)

- `GET  /v1/health` — liveness (sem token).
- `GET  /mcp/tools/list` — catálogo governado (com `capability`/`required_scope`/`resource_type`/`data_domain`).
- `POST /mcp/tools/call` — execução; exige inner Twin Token válido (`aud=mcp:frontend-mcp`, `jti`), exceto `status`.

O `tenant_id` vem **sempre** dos claims do inner token verificado, nunca de
argumento do cliente (SEC-035 / INV-3).

## Configuração

Copie `.env.example` para `.env` (gitignored) e ajuste. Discriminador de
ambiente: `RUNTIME_ENV ∈ {local, cloud}`. `DOCS_ENABLED` é `false` em todo
ambiente (STD-SEC-001) e, em `cloud`, `URL_ADMIN_TWIN_JWKS` é obrigatório
(STD-SEC-006) — ambos verificados no boot por `enforce_security_invariants()`.

## Desenvolvimento

```bash
cd frontend-mcp-server
pip install -e ".[dev]"
python -m ruff check .
python -m mypy src
python -m pytest -q --cov=src --cov-fail-under=80
```

Compliance: STD-MCP-001 (contrato de integração), STD-SEC-001/004/006
(segurança/segredos/inner token), STD-OBS-001 (logging estruturado JSON).
