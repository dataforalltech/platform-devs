# MCPs como Serviços HTTP Distribuídos - Arquitetura Completa

**Data:** 2026-05-10
**Status:** Ready for implementation
**Escopo:** 26 MCPs (18 system + 8 zilla) como serviços compartilhados

---

## Por que mudamos?

**Antes (Errado):**
```
Claude Code → stdio → subprocess MCP (único usuário)
```

**Problema:** Cada usuário precisa de seu próprio subprocess MCP. Não compartilhado.

**Agora (Correto):**
```
User 1 (Claude Code)  ──┐
User 2 (Python API)    ├──→ HTTP → Docker Network
User 3 (Node.js)       │
User 4 (Web)       ────┤   config-mcp:7100
                       ├──→ auth-mcp:7103
                       ├──→ archzilla-mcp:7118
                       └──→ ... (26 MCPs total)
```

**Vantagem:** Um único container MCP serve N usuários simultâneos.

---

## Arquitetura Final

```
┌─────────────────────────────────────────────────────────────┐
│                   Users & Clients                            │
│  Claude Code | Python | Node.js | Web UI | Codex | etc      │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP Requests
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   Docker Network (bridge)                    │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ config-mcp   │  │ auth-mcp     │  │ archzilla... │       │
│  │ :7100        │  │ :7103        │  │ :7118        │       │
│  │ FastAPI      │  │ FastAPI      │  │ Node.js      │       │
│  │ Python       │  │ Python       │  │ TypeScript   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ session-mcp  │  │ admin-mcp    │  │ backzilla... │       │
│  │ :7102        │  │ :7104        │  │ :7119        │       │
│  │ FastAPI      │  │ FastAPI      │  │ Node.js      │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         MCP Registry                                 │   │
│  │         (Service Discovery)                          │   │
│  │         :8000                                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  [PostgreSQL] [Redis] [SQLite] (Optional shared storage)    │
└──────────────────────────────────────────────────────────────┘
```

---

## Stack Técnico

### System MCPs (18 total)

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Framework | FastAPI |
| HTTP Server | Uvicorn |
| Ports | 7100-7117 |
| Containerization | Docker |
| Orchestration | Docker Compose |

**MCPs:**
- config-mcp (7100)
- agent-twin-mcp (7101)
- session-mcp (7102)
- auth-mcp (7103)
- admin-mcp (7104)
- audit-mcp (7105)
- infra-mcp (7106)
- services-mcp (7107)
- pipeline-mcp (7108)
- qa-mcp (7109)
- deploy-mcp (7110)
- docs-mcp (7111)
- ai-governance-mcp (7112)
- governance-mcp (7113)
- scheduler-mcp (7114)
- connectors-mcp (7115)
- cache-mcp (7116)
- test-mcp (7117)

### Zilla MCPs (8 total)

| Layer | Technology |
|-------|-----------|
| Language | TypeScript |
| Framework | MCP SDK Node.js |
| HTTP Server | Express (via MCP SDK) |
| Ports | 7118-7125 (external) / 7100 (internal) |
| Containerization | Docker |

**MCPs:**
- archzilla-mcp (7118)
- backzilla-mcp (7119)
- frontzilla-mcp (7120)
- opszilla-mcp (7121)
- pozilla-mcp (7122)
- productzilla-mcp (7123)
- qazilla-mcp (7124)
- seczilla-mcp (7125)

### Infrastructure

| Component | Technology | Port |
|-----------|-----------|------|
| MCP Registry | FastAPI | 8000 |
| Database (optional) | PostgreSQL | 5432 |
| Cache (optional) | Redis | 6379 |
| Networking | Docker bridge | - |

---

## HTTP API Padrão

Cada MCP expõe a mesma interface HTTP:

### Endpoints MCP (JSON-RPC via HTTP)

```
POST /mcp/initialize
POST /mcp/tools/list
POST /mcp/tools/call
```

### Health Endpoints

```
GET /health           → {"status": "healthy"}
GET /info             → {"name": "config-mcp", "tools": 10, ...}
GET /                 → Service info + links
```

### Exemplo: Call a tool

```bash
curl -X POST http://localhost:7100/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_config",
      "arguments": {"key": "database_url"}
    }
  }'
```

---

## Implementação Rápida

### 1. Testar config-mcp (FastAPI exemplo)

```bash
# Build
docker build -t config-mcp ./config-mcp-server

# Run
docker run -p 7100:7100 config-mcp

# Test
curl http://localhost:7100/health
curl http://localhost:7100/mcp/tools/list
```

### 2. Converter todos os 18 system MCPs

```bash
# Usar script automático
bash scripts/convert-all-mcps.sh

# Ou converter um por um
python scripts/convert-mcp-to-fastapi.py config-mcp 7100
python scripts/convert-mcp-to-fastapi.py auth-mcp 7103
```

### 3. Orquestrar com Docker Compose

```bash
# Start all 26 MCPs + registry
docker-compose up -d

# Check status
docker-compose ps

# Test
curl http://localhost:8000/services
```

---

## Migração Step by Step

### Phase 1: Template & Example (✅ Done)

- [x] Create FastAPI template (config-mcp example)
- [x] Create Dockerfile template
- [x] Create docker-compose.yml
- [x] Create MCP Registry for service discovery
- [x] Document architecture (this file)

### Phase 2: Conversion (Next - 2-3 hours)

- [ ] Run `bash scripts/convert-all-mcps.sh`
- [ ] Review generated code in each *-mcp-server/
- [ ] Implement tool dispatch logic (call_tool method)
- [ ] Test each MCP locally
- [ ] Build Docker images

### Phase 3: Orchestration (Next - 1 hour)

- [ ] `docker-compose build` (build all images)
- [ ] `docker-compose up -d` (start all MCPs)
- [ ] Verify health: `docker-compose ps` + curl /health
- [ ] Test Registry: curl `http://localhost:8000/services`
- [ ] Test individual MCPs: curl `http://localhost:7100/mcp/tools/list`

### Phase 4: Client Integration (Next - Variable)

- [ ] Create HTTP client wrapper for Claude Code (stdio ← HTTP)
- [ ] Or create MCP HTTP client library for Python/Node.js
- [ ] Update Claude Code .mcp.json to point to HTTP wrapper
- [ ] Test with multiple simultaneous users

### Phase 5: Production (Next)

- [ ] Deploy to Kubernetes or VM clusters
- [ ] Setup database for shared state (if needed)
- [ ] Setup Redis for caching (if needed)
- [ ] Configure monitoring & logging
- [ ] Setup auto-scaling policies

---

## Conectando Claude Code (3 opções)

### Opção A: HTTP Wrapper (Recomendado)

```python
# mcp-http-wrapper.py
# Claude Code → stdio → wrapper → HTTP → MCP services

import json, sys, requests

mcp_name = sys.argv[1]  # "config-mcp"
mcp_port = {"config-mcp": 7100, "auth-mcp": 7103, ...}[mcp_name]

while True:
    line = sys.stdin.readline()
    request = json.loads(line)
    
    response = requests.post(
        f"http://localhost:{mcp_port}/mcp/tools/call",
        json=request
    )
    
    sys.stdout.write(json.dumps(response.json()) + "\n")
    sys.stdout.flush()
```

**Vantagem:** Compatível com Claude Code atual
**Desvantagem:** Wrapper adicional

### Opção B: Python MCP Client

```python
# mcp_client.py
from typing import List, Dict
import httpx

class MCPClient:
    def __init__(self, url: str):
        self.url = url
        self.client = httpx.AsyncClient()
    
    async def list_tools(self) -> List[Dict]:
        resp = await self.client.get(f"{self.url}/mcp/tools/list")
        return resp.json()["result"]["tools"]
    
    async def call_tool(self, name: str, args: Dict) -> str:
        resp = await self.client.post(
            f"{self.url}/mcp/tools/call",
            json={"jsonrpc": "2.0", "id": 1, "params": {"name": name, "arguments": args}}
        )
        return resp.json()["result"]["content"][0]["text"]

# Usage
client = MCPClient("http://localhost:7100")
tools = await client.list_tools()
result = await client.call_tool("get_config", {"key": "db_url"})
```

**Vantagem:** Tipo-safe, Pythonic
**Desvantagem:** Usuários Python precisam instalar libraria

### Opção C: Direct HTTP (Sem Claude Code)

```bash
# Users usam curl ou HTTP client direto
curl -X POST http://localhost:7100/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"params":{"name":"get_config","arguments":{}}}'
```

**Vantagem:** Simples, sem dependencies
**Desvantagem:** Sem integração Claude Code

---

## Performance & Scaling

### Local Development

```bash
# Start all 26 MCPs locally
docker-compose up -d

# Resources
- CPU: ~500m (all MCPs combined)
- Memory: ~500MB (all MCPs combined)
- Disk: ~2GB (Docker images + containers)
```

### Production (Kubernetes)

```yaml
# Scale individual MCPs
kubectl scale deployment config-mcp --replicas=3
kubectl scale deployment archzilla-mcp --replicas=2

# Load Balancer
apiVersion: v1
kind: Service
metadata:
  name: config-mcp
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 7100
  selector:
    app: config-mcp
```

### Multi-Server Deployment

```
[Server 1: 10 MCPs]        [Server 2: 10 MCPs]        [Server 3: Registry + DB]
  config-mcp:7100           archzilla-mcp:7100          mcp-registry:8000
  auth-mcp:7103             backzilla-mcp:7100          postgresql:5432
  session-mcp:7102          ... more zillas ...         redis:6379
  ... more system MCPs ...

[Load Balancer]
  routes requests to appropriate server
```

---

## Monitoramento & Observability

### Health Checks

```bash
# Individual MCP
curl http://localhost:7100/health

# All MCPs (via registry)
curl http://localhost:8000/stats
```

### Logging

```bash
# Docker logs
docker-compose logs -f config-mcp

# All MCPs
docker-compose logs -f
```

### Metrics (Optional)

```python
# Add to FastAPI
from prometheus_client import Counter, Histogram
import time

tool_calls = Counter('mcp_tool_calls', 'Tool calls', ['mcp_name', 'tool_name'])
tool_duration = Histogram('mcp_tool_duration_seconds', 'Tool duration', ['mcp_name'])

@app.post("/mcp/tools/call")
async def call_tool(request):
    start = time.time()
    tool_calls.labels(mcp_name="config-mcp", tool_name=request.params["name"]).inc()
    result = service.call_tool(...)
    tool_duration.labels(mcp_name="config-mcp").observe(time.time() - start)
    return result
```

---

## Troubleshooting

### "Connection refused"

```bash
docker-compose ps
docker-compose logs config-mcp
netstat -tlnp | grep 7100
```

### "Health check failed"

```bash
curl http://localhost:7100/health
docker-compose logs --tail=50 config-mcp
```

### "Tool not found"

```bash
curl http://localhost:7100/mcp/tools/list
# Verify tool name is correct
```

---

## Referências

- FastAPI: https://fastapi.tiangolo.com/
- Docker Compose: https://docs.docker.com/compose/
- MCP Spec: https://modelcontextprotocol.io/
- Uvicorn: https://www.uvicorn.org/

---

## Checklist Final

- [ ] Phase 1: Example + Templates ✅
- [ ] Phase 2: Convert all 18 system MCPs
- [ ] Phase 3: Orquestrate com docker-compose
- [ ] Phase 4: Criar HTTP wrapper para Claude Code
- [ ] Phase 5: Deploy to production
- [ ] Phase 6: Setup monitoring & alerting

---

**Próximo passo:** Executar `bash scripts/convert-all-mcps.sh` para converter todos os 18 system MCPs
