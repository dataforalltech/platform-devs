# MCP Health Check Standard

## Endpoint

Todos os MCP servers Python expõem:

```
GET /v1/health
```

Resposta esperada (HTTP 200):

```json
{"status": "ok", "service": "<nome-do-mcp>"}
```

## Portas

| Serviço            | Porta interna | Porta host |
|--------------------|--------------|------------|
| agent-twin-mcp     | 7100         | 27101      |
| config-mcp         | 7099         | 27102      |
| session-mcp        | 7100         | 27103      |
| audit-mcp          | 7100         | 27104      |
| deploy-mcp         | 7100         | 27105      |
| docs-mcp           | 7100         | 27106      |
| infra-mcp          | 7100         | 27107      |
| pipeline-mcp       | 7100         | 27108      |
| qa-mcp             | 7100         | 27109      |
| services-mcp       | 7100         | 27110      |
| test-mcp           | 7100         | 27111      |
| ai-governance-mcp  | 7100         | 27112      |

> config-mcp usa porta 7099 por convenção histórica. Defina `MCP_PORT=7099` no ambiente.

## Docker Compose healthcheck

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:7100/v1/health', timeout=5)"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 5s
```

## Padrão de implementação

### `_build_http_app()`

Toda FastAPI app interna deve incluir `/v1/health` antes de qualquer outro endpoint:

```python
def _build_http_app() -> FastAPI:
    app = FastAPI(title="<nome>-mcp API", version="0.1.0", docs_url="/docs")

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "service": "<nome>-mcp"}

    return app
```

### `build_server()` — retorno obrigatório

O `http_app` **deve ser o último elemento** do tuple retornado, pois `_run()` usa `rest[-1]`:

```python
def build_server() -> tuple[Any, ...]:
    ...
    http_app = _build_http_app()
    ...
    return server, settings, store, http_app  # http_app sempre por último
```

### `_run()`

```python
async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, *rest = build_server()
    http_app = rest[-1]  # depende de http_app ser o último no tuple

    cfg = uvicorn.Config(
        http_app, host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7100")),
        log_level="warning", access_log=False,
    )
    server_http = uvicorn.Server(cfg)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await asyncio.gather(
                server.run(read_stream, write_stream, server.create_initialization_options()),
                server_http.serve(),
            )
    except (EOFError, BrokenPipeError):
        pass
```

## Armadilhas conhecidas

| Problema | Causa | Solução |
|----------|-------|---------|
| `TypeError: 'XxxStore' object is not callable` | `build_server()` não inclui `http_app` no return | Adicionar `http_app` como último elemento do tuple |
| HTTP 404 em `/v1/health` | `_build_http_app()` sem a rota, ou router com `prefix="/v1"` e rota `"/v1/health"` | Adicionar rota, ou corrigir para `"/health"` dentro do router prefixado |
| `Connection refused` | `MCP_PORT` não definido e uvicorn sobe em porta diferente da exposta | Definir `MCP_PORT` no docker-compose igual à porta do container |
