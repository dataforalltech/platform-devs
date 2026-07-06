# Registrar backends MCP no gateway (services / qa / deploy)

> Objetivo: fazer `services-mcp`, `qa-mcp`, `deploy-mcp` aparecerem no catálogo do
> gateway `platform-mcp` (hoje 88 tools de `admin`/`auth`/`api-gateway`), para os
> runbooks do DevTeam (`health_to_report`, `deploy_service`) fecharem verde.
> **Nada aqui foi aplicado — é decisão de infra + envolve o gateway compartilhado.**

## Por que não é um INSERT simples

O gateway monta o catálogo de um **ServiceRegistry** com 3 fontes (`REGISTRY_SOURCE`):
`env` (`TWIN_GATEWAY_SERVICES` JSON) · `db` (tabela `ADMIN_DATAFORALL.GATEWAY_MAPPING`) ·
`api` (endpoint do admin `/api/v1/internal/gateway/registry`).

Dois fatos que complicam:

1. **A `GATEWAY_MAPPING` real NÃO tem as colunas MCP.** Colunas reais: `name_microservice,
   internal_url, path_prefix, strip_prefix, public_paths, health_path, additional_info(JSON),
   circuit_breaker_*`. **Faltam** `kind`, `mcp_url`, `tools_list_path`, `tools_call_path`,
   `call_style` — que o `platform-mcp/app/registry/sources.py::rows_to_services()` espera para
   um backend `kind=mcp_http`. O `load_from_db()` é defensivo: se a coluna não existe, assume
   `kind='rest'`. Por isso `admin`/`auth`/`api-gateway` entram como **REST** e o gateway gera
   as tools a partir do `/openapi.json` deles (os "75 tools" do admin = endpoints REST). Os 3
   backends são **MCP nativo** (Streamable HTTP), então precisam de `kind=mcp_http` + `mcp_url` —
   que a tabela atual não expressa.

2. **O `admin` endpoint só devolve 4 colunas** (`name_microservice, internal_url, health_path,
   timeout_seconds`) — não repassa config MCP. E o `sources.py` atual **não lê `additional_info`**.

> ⚠️ Confirmar o `REGISTRY_SOURCE` do gateway EM EXECUÇÃO antes de agir (a stack estava parada
> na investigação): `docker exec platform-mcp printenv | grep -E "REGISTRY_SOURCE|TWIN_GATEWAY_SERVICES"`.
> O `.env.dev` do repo diz `REGISTRY_SOURCE=env` + `TWIN_GATEWAY_SERVICES=[]`, mas como HÁ 88 tools
> registradas, o container real usa `db`/`api` (lê a `GATEWAY_MAPPING`). Decidir o caminho depende disso.

## Caminhos (escolher UM)

### Caminho 1 — `REGISTRY_SOURCE=env` + `TWIN_GATEWAY_SERVICES` (mais simples em dev)
Trocar a fonte para `env` e listar os 3 backends. **Custo:** sai da `db` → você perde
`admin`/`auth`/`api-gateway` do catálogo, a menos que os inclua também no JSON. Só vale se o
JSON reproduzir TODOS os backends.

```jsonc
// TWIN_GATEWAY_SERVICES (confirmar as PORTAS host reais no platform-devs/docker-compose.yml)
[
  {"name":"platform-services","namespace":"services","kind":"mcp_http",
   "mcp_url":"http://host.docker.internal:27110","audience":"mcp:services",
   "tools_list_path":"/mcp/tools/list","tools_call_path":"/mcp/tools/call","call_style":"mcp","health_path":"/v1/health"},
  {"name":"platform-qa","namespace":"qa","kind":"mcp_http",
   "mcp_url":"http://host.docker.internal:27109","audience":"mcp:qa",
   "tools_list_path":"/mcp/tools/list","tools_call_path":"/mcp/tools/call","call_style":"mcp","health_path":"/v1/health"},
  {"name":"platform-deploy","namespace":"deploy","kind":"mcp_http",
   "mcp_url":"http://host.docker.internal:27105","audience":"mcp:deploy",
   "tools_list_path":"/mcp/tools/list","tools_call_path":"/mcp/tools/call","call_style":"mcp","health_path":"/v1/health"}
]
```
Depois: `docker restart platform-mcp` (ou aguardar `CATALOG_REFRESH_SECONDS`).

> Nota: confirmar o path MCP real dos backends — o `qa-mcp-server` expõe `/mcp/tools/list`
> (Streamable HTTP). NÃO use `/v1/tools` (esse é o estilo do admin-mcp legado).

### Caminho 2 — `REGISTRY_SOURCE=db` + colunas MCP na `GATEWAY_MAPPING` (modo cloud)
Preserva `admin`/`auth`/`api-gateway`. Requer **ALTER TABLE** (mudança de schema — validar impacto):

```sql
ALTER TABLE GATEWAY_MAPPING
  ADD COLUMN kind            VARCHAR(32)  DEFAULT 'rest',
  ADD COLUMN mcp_url         VARCHAR(512),
  ADD COLUMN tools_list_path VARCHAR(256) DEFAULT '/mcp/tools/list',
  ADD COLUMN tools_call_path VARCHAR(256) DEFAULT '/mcp/tools/call',
  ADD COLUMN call_style      VARCHAR(32)  DEFAULT 'mcp';

INSERT INTO GATEWAY_MAPPING
  (name_microservice, mcp_url, kind, health_path, timeout_seconds, tools_list_path, tools_call_path, call_style)
VALUES
  ('platform-services','http://host.docker.internal:27110','mcp_http','/v1/health',30,'/mcp/tools/list','/mcp/tools/call','mcp'),
  ('platform-qa',      'http://host.docker.internal:27109','mcp_http','/v1/health',30,'/mcp/tools/list','/mcp/tools/call','mcp'),
  ('platform-deploy',  'http://host.docker.internal:27105','mcp_http','/v1/health',30,'/mcp/tools/list','/mcp/tools/call','mcp');
```
Alinhar as migrations do `platform-mcp` para não divergir de novo.

### Caminho 3 — `additional_info` JSON (sem ALTER, mas exige código)
Guardar a config MCP no JSON `additional_info`. **Bloqueado hoje:** `sources.py` não lê
`additional_info` — precisaria de um patch no gateway para parsear esse campo. Só se você quiser
evitar ALTER e topar mexer no código do gateway.

## Depois de registrar: repontar os runbooks (código nosso)

O namespace vira `nome − "platform-"` → `services`/`qa`/`deploy`. Os **operationIds REAIS**
(diferentes do que os runbooks assumem hoje):

| Runbook usa hoje | Tool real no gateway | Existe? |
|---|---|---|
| `services-mcp.check_health` | `services.check_health` | ✅ (services-mcp tem `check_health`) |
| `qa-mcp.run_tests` | `qa.run_unit_tests` | ⚠️ não existe `run_tests` |
| `qa-mcp.generate_report` | `qa.generate_qa_report` | ⚠️ nome diferente |
| `deploy-mcp.create_deployment` | `deploy.deploy` | ⚠️ nome diferente |

**services-mcp (32):** register_service, list_services, check_health, check_all_health, service_status, get_port_map, scan_docker, kafka_status, redis_status, get_service_logs, … 
**qa-mcp (14):** run_unit_tests, run_e2e_tests, run_api_tests, run_linter, run_security_scan, get_coverage_report, generate_qa_report, check_accessibility, … 
**deploy-mcp (24):** list_repos, create_branch, commit_files, create_pr, merge_pr, deploy, get_deploy_status, trigger_workflow, acr_build, clone_repo, …

> Só repontar os runbooks (`health_to_report`, `deploy_service`) **depois** de registrar e ver os
> tool ids reais no `/mcp/tools/list` — o namespace/paths dependem do caminho escolhido.

## Checklist
1. Subir os 3 backends e validar `curl http://localhost:2711X/mcp/tools/list`.
2. Confirmar `REGISTRY_SOURCE` do gateway em execução.
3. Registrar pelo caminho 1 **ou** 2 (não misturar).
4. `docker restart platform-mcp` → validar no `/mcp/tools/list` (`services.*`, `qa.*`, `deploy.*`).
5. Repontar `health_to_report`/`deploy_service` para os operationIds reais + atualizar o `_fake_gateway`/testes.
