# MCP Hybrid Server Conversion Pattern

## Status: 10 of 12 System MCPs Converted ✅

### Completed Conversions ✅
- **agent-twin-mcp** — Authentication & identity (HTTP on 7100, docker port 7101:7100)
- **config-mcp** — Credentials & environment (HTTP on 7100, docker port 7102:7100)
- **8 Zillas** — All converted (archzilla, backzilla, frontzilla, opszilla, pozilla, productzilla, qazilla, seczilla)

### Remaining to Convert ⏳
- **session-mcp** — Session & task management
- **audit-mcp** — Audit logging & governance
- **deploy-mcp** — GitHub & deployment
- **docs-mcp** — Documentation
- **infra-mcp** — Infrastructure & ADRs
- **pipeline-mcp** — CI/CD & gates
- **qa-mcp** — Testing & quality
- **services-mcp** — Service registry
- **test-mcp** — Test planning
- **ai-governance-mcp** — AI governance

---

## Conversion Pattern

Each Python MCP server needs these changes to run in hybrid mode (stdio + HTTP on port 7100):

### 1. Update `src/server/mcp_server.py`

**Change 1a:** Remove old HTTP threading code
```python
# REMOVE THIS:
import threading
def _start_http_api(...) -> None:
    app = FastAPI(...)
    router = make_router(...)
    app.include_router(router)
    cfg = uvicorn.Config(app, host="127.0.0.1", port=settings.api_port, ...)
    server = uvicorn.Server(cfg)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
```

**Change 1b:** Create new HTTP app builder function
```python
def _build_http_app(...) -> FastAPI:
    """Build FastAPI app for HTTP on port 7100."""
    app = FastAPI(title="...", version="0.1.0", docs_url="/docs")
    router = make_router(...)  # or make_routes(...) — check your existing code
    app.include_router(router)
    return app
```

**Change 1c:** Update `build_server()` return type and initialization
```python
# BEFORE:
def build_server() -> tuple[Server, ConfigStore, ConfigMcpSettings]:
    settings = get_settings()
    store = ConfigStore(...)
    if settings.api_enabled:
        _start_http_api(store, settings)  # REMOVE THIS
    ...
    return server, store, settings

# AFTER:
def build_server() -> tuple[Any, ConfigStore, ConfigMcpSettings, FastAPI]:
    settings = get_settings()
    store = ConfigStore(...)
    http_app = _build_http_app(store, settings)  # ADD THIS
    ...
    return server, store, settings, http_app
```

**Change 1d:** Update `_run()` to run both protocols concurrently
```python
# BEFORE:
async def _run() -> None:
    server, _store, _settings = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

# AFTER:
async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, _store, _settings, http_app = build_server()

    cfg = uvicorn.Config(
        http_app, host="0.0.0.0", port=7100,
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

---

### 2. Update `Dockerfile`

**BEFORE:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.104.1 uvicorn[standard]==0.24.0
COPY ./my_mcp_server.py .
EXPOSE 7100
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:7100/health')" || exit 1
CMD ["python3", "-m", "uvicorn", "my_mcp_server:app", "--host", "0.0.0.0", "--port", "7100"]
```

**AFTER:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY {mcp-name}-server/pyproject.toml .
COPY {mcp-name}-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7100
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7100/health || exit 1
CMD ["{mcp-name}-server"]
```

---

### 3. Update `docker-compose.yml`

For each MCP, add a service definition:
```yaml
  {mcp-name}-mcp:
    build:
      context: .
      dockerfile: {mcp-name}-mcp-server/Dockerfile
    ports:
      - "{external_port}:7100"  # e.g., "7103:7100" for session-mcp
    environment:
      PYTHONPATH: /app:/app/shared
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7100/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s
    networks:
      - mcp-network
    restart: unless-stopped
    labels:
      - "mcp={mcp-name}-mcp"
      - "type=system"
      - "language=python"
```

**Port Mapping Convention:**
- agent-twin-mcp: 7101:7100
- config-mcp: 7102:7100
- session-mcp: 7103:7100
- audit-mcp: 7104:7100
- deploy-mcp: 7105:7100
- docs-mcp: 7106:7100
- infra-mcp: 7107:7100
- pipeline-mcp: 7108:7100
- qa-mcp: 7109:7100
- services-mcp: 7110:7100
- test-mcp: 7111:7100
- ai-governance-mcp: 7112:7100

---

### 4. Update `mcp-gateway/src/proxy/router.py`

Add each MCP to the `MCP_REGISTRY`:
```python
MCP_REGISTRY = {
    "agent-twin-mcp": "http://agent-twin-mcp:7100",
    "config-mcp": "http://config-mcp:7100",
    "session-mcp": "http://session-mcp:7100",  # ADD
    # ... etc
}
```

---

### 5. Update gateway's `depends_on`

In `docker-compose.yml` mcp-gateway service:
```yaml
depends_on:
  - redis
  - postgres
  - agent-twin-mcp
  - config-mcp
  - session-mcp    # ADD
  - audit-mcp      # ADD
  # ... etc (add all MCPs as you convert them)
```

---

## Implementation Order (Priority)

1. **session-mcp** — Required for session-init protocol
2. **audit-mcp** — Required for auditoria/governance
3. **deploy-mcp** — Required for git/PR operations
4. **qa-mcp** — Required for testing & validation
5. **test-mcp** — Companion to qa-mcp
6. **services-mcp** — Service registry & health checks
7. **infra-mcp** — Infrastructure & ADRs
8. **docs-mcp** — Documentation & templates
9. **pipeline-mcp** — CI/CD gates
10. **ai-governance-mcp** — AI governance policies

---

## Quick Conversion Script

For efficiency, you can convert multiple MCPs at once using find/sed:

```bash
# Update all remaining MCPs at once
for mcp in session-mcp audit-mcp deploy-mcp qa-mcp test-mcp services-mcp infra-mcp docs-mcp pipeline-mcp ai-governance-mcp; do
  echo "Converting $mcp..."
  # 1. Apply mcp_server.py changes
  # 2. Update Dockerfile
  # 3. Add to docker-compose.yml
  # 4. Add to MCP_REGISTRY
done
```

---

## Verification Checklist

After converting each MCP:
- [ ] Dockerfile builds successfully: `docker compose build {mcp-name}-mcp`
- [ ] Service runs: `docker compose up {mcp-name}-mcp` (should start without errors)
- [ ] HTTP endpoint works: `curl http://localhost:{port}/health`
- [ ] Added to MCP_REGISTRY in router.py
- [ ] Added to docker-compose depends_on if critical

---

## Testing the Full Stack

Once all MCPs are converted:

```bash
# Start all services
docker compose up -d

# Verify all MCPs are running
docker compose ps

# Test gateway proxy
curl -H "Authorization: Bearer test-developer-token" \
  http://localhost:8080/mcp/session-mcp/tools

# Test rate limiting
curl -H "Authorization: Bearer test-readonly-token" \
  http://localhost:8080/mcp/qazilla-mcp/tools/call \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"name":"test","arguments":{}}'
```

---

## Key Design Decisions

1. **Port 7100 Internal**: All MCPs run on 7100 internally for consistency
2. **External Mapping**: External ports vary (7101+) to avoid conflicts on host
3. **asyncio.gather()**: Runs stdio and HTTP concurrently in same process
4. **Docker Network**: All MCPs on same mcp-network, accessed by hostname
5. **Shared PYTHONPATH**: Allows imports from shared/ directory

---

## Notes

- **Existing API Routes**: If an MCP has custom API routes (like config-mcp's router), reuse them via `app.include_router()`
- **Port Configuration**: Check if any MCP's settings.py reads a port from environment - ensure it uses 7100 or ignore it
- **Database Connections**: Most MCPs have internal DB/store initialization in build_server() - preserve this
- **Error Handling**: The try/except EOFError/BrokenPipeError is expected for clean shutdown

