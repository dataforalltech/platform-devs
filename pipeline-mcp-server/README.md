# pipeline-mcp-server

MCP Server responsável pelo gerenciamento de pipeline DEV→HML→PROD para microserviços da plataforma dataforalltech.

## Responsabilidades

- Gerenciar status de pipeline de cada microserviço: `dev | homol | prod | blocked | rollback`
- Ser o único que pode promover um serviço entre ambientes (DEV→HML→PROD)
- Orquestrar branches: `develop` → `homol` → `main` via deploy-mcp HTTP API
- Executar autonomamente o merge quando todos os gates passam
- Registrar histórico completo de promoções com quem, quando, por quê

## Tools (12)

### Pipeline (6)
- `register_pipeline` — registra serviço no pipeline
- `get_pipeline` — status atual + histórico de promoções
- `list_pipeline` — lista serviços com filtros
- `promote_service` — promove DEV→HML ou HML→PROD após verificar gates
- `block_service` — bloqueia promoção de um serviço
- `rollback` — faz rollback de versão

### Gates (3)
- `add_gate_result` — registra resultado de um gate
- `get_gate_status` — retorna status de todos os gates
- `clear_gates` — limpa gates para re-avaliação

### Histórico (3)
- `get_promotion_history` — histórico de promoções
- `get_pipeline_overview` — visão geral por ambiente
- `set_pipeline_config` — configura gates obrigatórios por serviço

## Configuração (env vars)

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `PIPELINE_DB_PATH` | `~/.pipeline-mcp/pipeline.db` | Caminho do banco SQLite |
| `PIPELINE_API_PORT` | `7101` | Porta da HTTP API sidecar |
| `PIPELINE_API_ENABLED` | `true` | Habilitar HTTP API |
| `PIPELINE_DEPLOY_MCP_URL` | `http://127.0.0.1:7100` | URL do deploy-mcp |

## HTTP API (porta 7101)

- `GET /api/health` — health check
- `GET /v1/pipeline/{service}` — status de um serviço

## Instalação

```bash
cd pipeline-mcp-server
pip install -e .
pipeline-mcp-server
```
