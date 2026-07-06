# E2E contra o gateway real (`platform-mcp`)

O `tests/test_e2e_local.py::test_e2e_local_read_pipeline_all_done` prova a cadeia
completa (RUNBOOK → PlanBuilder → PlanRepository → PlanExecutor → GatewayToolClient)
sobre **transporte httpx real** (JSON-RPC), usando um gateway-fake in-process
(`ASGITransport`). Este doc explica como apontar o **mesmo** caminho para o
`platform-mcp` **real**, sem mudar nenhum componente — só configuração.

> Base factual: leitura de `platform-mcp` (app/main.py, .env.example, README, CLAUDE.md).

## 1. O que o cliente precisa mandar

O `GatewayToolClient` já fala o protocolo certo (JSON-RPC `tools/call` Streamable HTTP).
Para o gateway real, atente a **três** coisas:

| Requisito | Valor | Onde |
|---|---|---|
| **Endpoint** | `http://<host>:8085/mcp` (JSON-RPC) — **não** `/mcp/tools/call` (esse é o alias REST com body `{"params":{…}}`) | `base_url` |
| **`Authorization`** | `Bearer <Twin Token>` (JWT RS256, `aud=mcp:gateway`, emitido pelo platform-admin) | `token_provider.get_token()` |
| **`X-Tenant-Id`** | obrigatório (SEC-035) — o gateway rejeita sem ele | `tenant_id=` no `executor.execute(...)` → `build_correlation` → header |

O gateway faz a troca RFC 8693 internamente (Twin Token `aud=mcp:gateway` →
inner token `aud=mcp:<svc>`, TTL 60s) antes de encaminhar ao backend.

## 2. Subir o gateway (receita mínima read-only)

```bash
cd ../platform-mcp   # repo irmão
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -r requirements.txt

# infra opcional em dev (evitável — ver flags abaixo)
docker compose -f docker-compose.dev.yml up -d      # MySQL 53306 + Redis 6379

cat > .env <<'EOF'
ENVIRONMENT=development
GATEWAY_AUDIENCE=mcp:gateway

# platform-admin (8002) é OBRIGATÓRIO: JWKS p/ verificar o token + exchange
URL_ADMIN_TWIN_JWKS=http://localhost:8002/api/v1/twin/jwks.json
ADMIN_EXCHANGE_URL=http://localhost:8002/api/v1/twin/exchange

# evita banco/redis em dev
REGISTRY_SOURCE=env
REVOCATION_ENABLED=false
TRACE_DB_ENABLED=false

# 1 tool read-only registrada; exempt=true pula PEP/exchange (forward direto)
TWIN_GATEWAY_SERVICES=[{"name":"services-mcp","namespace":"services-mcp","kind":"rest","baseUrl":"http://localhost:7XXX","audience":"mcp:services","tools":[{"name":"check_health","method":"GET","path":"/v1/health","exempt":true}]}]
EOF

make run-dev     # uvicorn app.main:app --port 8085
curl http://localhost:8085/api/health/ready   # {"status":"healthy","tools":N}
```

**Dependência dura:** o `platform-admin` (8002) precisa estar de pé para o gateway
verificar o Bearer (JWKS) — ou mocar o JWKS. Uma tool `exempt:true` pula
PEP/exchange (não precisa de backend/governance), mas a **verificação do token**
ainda ocorre. MySQL/Redis são evitáveis com as flags acima.

## 3. Rodar o E2E real

```bash
cd ../platform-dev-agent
export DEV_GATEWAY_URL="http://localhost:8085/mcp"     # termina em /mcp
export DEV_TENANT_ID="PLATFORM_DEV_30"                  # vira X-Tenant-Id
export DEV_GATEWAY_TOKEN="<Twin Token aud=mcp:gateway>" # do platform-admin
python -m pytest -q tests/test_e2e_local.py::test_e2e_against_real_gateway
```

Sem `DEV_GATEWAY_URL`, esse teste fica *skipped* — o E2E local (fake) continua
provando o transporte a cada `pytest`.

## 4. Idempotência & resume (por que write ≠ read aqui)

O gateway **não deduplica efeito de write** por `Idempotency-Key` — ele só evita
**retentar** writes (`is_idempotent` → retry apenas de reads). Por isso o
`GatewayToolClient` só aplica retry a reads, e o executor trata write órfão
(`EXECUTING` no crash) como `NEEDS_RECONFIRM` (reconfirmação humana), nunca replay.
`Settings.resume_writes_safe=False`. Ver `PLATFORM_DEV_AGENT_SPEC.md` §4.
