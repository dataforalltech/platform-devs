# MCPs como Serviços Distribuídos: FastAPI + Docker

**Arquitetura nova:** MCPs rodam como servidores HTTP independentes em Docker, compartilhados por N usuários.

---

## Visão Geral

```
User 1 (Claude Code)  ──┐
User 2 (Python API)    ├──→ Docker Network
User 3 (Node.js)       ├──→ [26 MCP Services on HTTP]
User 4 (Web)       ────┤
                       ├──→ MCP Registry (8000)
                       └──→ Database (shared state)
```

**Cada MCP:**
- Roda como container Docker independente
- HTTP server (FastAPI)
- Escuta em porta única (7100-7125)
- Aceita múltiplas conexões simultâneas
- Compartilhado por todos os usuários

---

## Stack Padrão

| Componente | Padrão |
|------------|--------|
| Framework | FastAPI (Python) |
| HTTP Server | Uvicorn |
| Containerization | Docker + Docker Compose |
| Language (System MCPs) | Python 3.11 |
| Language (Zilla MCPs) | Node.js (TypeScript transpiled) |
| Service Discovery | MCP Registry (HTTP) |
| Networking | Docker bridge network |

---

## Estrutura de um MCP FastAPI

### 1. Service Class (Domain Logic)

```python
class MyServiceMCP:
    def __init__(self):
        self.name = "my-service-mcp"
        self.tools = [...]  # Define tools
    
    def list_tools(self) -> List[Dict]:
        return self.tools
    
    def call_tool(self, tool_name: str, args: Dict) -> str:
        # Implementar cada tool
        if tool_name == "do_something":
            return "Done"
```

### 2. FastAPI Routes

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
service = MyServiceMCP()

@app.post("/mcp/initialize")
async def initialize(request: MCPRequest) -> MCPResponse:
    result = service.initialize(request.id)
    return MCPResponse(id=request.id, result=result)

@app.post("/mcp/tools/call")
async def call_tool(request: MCPRequest) -> MCPResponse:
    result = service.call_tool(request.params["name"], request.params["arguments"])
    return MCPResponse(id=request.id, result={"content": [{"type": "text", "text": result}]})

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### 3. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
RUN pip install fastapi uvicorn pydantic

COPY my_service_mcp.py .

EXPOSE 7100
HEALTHCHECK CMD curl -f http://localhost:7100/health || exit 1

CMD ["python3", "-m", "uvicorn", "my_service_mcp:app", "--host", "0.0.0.0", "--port", "7100"]
```

### 4. Docker Compose Entry

```yaml
services:
  my-service-mcp:
    build:
      context: ./my-service-mcp-server
      dockerfile: Dockerfile
    ports:
      - "7100:7100"
    environment:
      PORT: 7100
    networks:
      - mcp-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7100/health"]
      interval: 30s
```

---

## Portas Alocadas

### System MCPs (Python) - 7100-7117

| MCP | Porta |
|-----|-------|
| config-mcp | 7100 |
| agent-twin-mcp | 7101 |
| session-mcp | 7102 |
| auth-mcp | 7103 |
| admin-mcp | 7104 |
| audit-mcp | 7105 |
| infra-mcp | 7106 |
| services-mcp | 7107 |
| pipeline-mcp | 7108 |
| qa-mcp | 7109 |
| deploy-mcp | 7110 |
| docs-mcp | 7111 |
| ai-governance-mcp | 7112 |
| governance-mcp | 7113 |
| scheduler-mcp | 7114 |
| connectors-mcp | 7115 |
| cache-mcp | 7116 |
| test-mcp | 7117 |

### Zilla MCPs (Node.js) - 7118-7125

| MCP | Porta (Externa) | Porta (Interna) |
|-----|-----------------|-----------------|
| archzilla-mcp | 7118 | 7100 |
| backzilla-mcp | 7119 | 7100 |
| frontzilla-mcp | 7120 | 7100 |
| opszilla-mcp | 7121 | 7100 |
| pozilla-mcp | 7122 | 7100 |
| productzilla-mcp | 7123 | 7100 |
| qazilla-mcp | 7124 | 7100 |
| seczilla-mcp | 7125 | 7100 |

### Gateway & Registry

| Serviço | Porta |
|---------|-------|
| MCP Registry | 8000 |

---

## Como Usar

### 1. Iniciar todos os MCPs

```bash
docker-compose up -d

# Verificar status
docker-compose ps

# Ver logs
docker-compose logs -f config-mcp
```

### 2. Testar um MCP

```bash
# Health check
curl http://localhost:7100/health

# MCP Initialize
curl -X POST http://localhost:7100/mcp/initialize \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    }
  }'

# List tools
curl http://localhost:7100/mcp/tools/list

# Call a tool
curl -X POST http://localhost:7100/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get_config",
      "arguments": {"key": "database_url"}
    }
  }'
```

### 3. Service Discovery (Registry)

```bash
# List all MCPs
curl http://localhost:8000/services

# Get stats
curl http://localhost:8000/stats

# Get specific MCP
curl http://localhost:8000/services/config-mcp

# List by type
curl http://localhost:8000/services/type/system
curl http://localhost:8000/services/type/zilla

# Get auto-generated config
curl http://localhost:8000/config
```

---

## Conectando Claude Code

### Opção 1: HTTP Direct

Ao invés de stdio, Claude Code conecta via HTTP:

```json
{
  "mcpServers": {
    "config-mcp": {
      "command": "curl",
      "args": ["-X", "POST", "http://localhost:7100/mcp/tools/call"]
    }
  }
}
```

**Problema:** Claude Code não suporta HTTP nativamente no .mcp.json

### Opção 2: Wrapper HTTP → Stdio (Recomendado)

Criar um wrapper que:
1. Claude Code conecta via stdio ao wrapper
2. Wrapper converte para HTTP requests
3. Wrapper faz request para MCPs (7100-7125)
4. Retorna resposta via stdio

```python
#!/usr/bin/env python3
# mcp-http-wrapper.py
import json
import sys
import requests

# Lê requests do Claude via stdin
while True:
    line = sys.stdin.readline()
    msg = json.loads(line)
    
    # Converte para HTTP
    mcp_name = sys.argv[1]  # config-mcp, etc
    mcp_port = 7100 + MCP_PORTS[mcp_name]
    
    response = requests.post(
        f"http://localhost:{mcp_port}/mcp/tools/call",
        json=msg
    )
    
    # Retorna via stdout
    sys.stdout.write(json.dumps(response.json()) + "\n")
    sys.stdout.flush()
```

### Opção 3: Python MCP Client Library

Criar biblioteca Python que conecta aos MCPs HTTP:

```python
from mcp_client import MCPClient

client = MCPClient("http://localhost:7100")
tools = client.list_tools()
result = client.call_tool("get_config", {"key": "db_url"})
```

---

## Exemplo Completo: Criar novo MCP em FastAPI

### 1. Template

```bash
mkdir my-domain-mcp-server
cd my-domain-mcp-server
touch my_domain_mcp.py Dockerfile docker-compose.override.yml
```

### 2. my_domain_mcp.py

```python
from fastapi import FastAPI
from pydantic import BaseModel
import os
import uvicorn

app = FastAPI(title="My Domain MCP", version="1.0")

class MyDomainService:
    def __init__(self):
        self.name = "my-domain-mcp"
        self.tools = [
            {
                "name": "tool_1",
                "description": "Does something",
                "inputSchema": {"type": "object", "properties": {}}
            }
        ]

service = MyDomainService()

@app.post("/mcp/tools/call")
async def call_tool(request: dict):
    tool_name = request["params"]["name"]
    result = f"Tool {tool_name} executed"
    return {"jsonrpc": "2.0", "id": request["id"], "result": {"content": [{"type": "text", "text": result}]}}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7126))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

### 3. Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn
COPY my_domain_mcp.py .
EXPOSE 7126
CMD ["python3", "-m", "uvicorn", "my_domain_mcp:app", "--host", "0.0.0.0", "--port", "7126"]
```

### 4. Adicionar ao docker-compose.yml

```yaml
my-domain-mcp:
  build:
    context: ./my-domain-mcp-server
  ports:
    - "7126:7126"
  environment:
    PORT: 7126
  networks:
    - mcp-network
```

### 5. Rodar

```bash
docker-compose up -d my-domain-mcp
curl http://localhost:7126/health
```

---

## Checklist de Migração (Cada MCP)

- [ ] Renomear arquivo: `config-mcp.py` → `config_mcp.py`
- [ ] Converter para FastAPI:
  - [ ] Remover stdin/stdout loop
  - [ ] Adicionar `@app.post("/mcp/...")` rotas
  - [ ] Adicionar `@app.get("/health")`
  - [ ] Adicionar models Pydantic (MCPRequest, MCPResponse)
- [ ] Criar Dockerfile com FastAPI
- [ ] Adicionar ao docker-compose.yml
- [ ] Testar localmente: `python config_mcp.py`
- [ ] Testar em Docker: `docker build . && docker run -p 7100:7100 ...`
- [ ] Testar com curl: `curl http://localhost:7100/mcp/tools/list`

---

## Troubleshooting

### "Connection refused"

```bash
# Verificar se container está rodando
docker-compose ps

# Ver logs
docker-compose logs config-mcp

# Verificar porta
netstat -tlnp | grep 7100
```

### "Health check failed"

```bash
# Testar health endpoint
curl http://localhost:7100/health

# Ver logs do container
docker-compose logs --tail=50 config-mcp
```

### "Tool not found"

```bash
# Verificar tools disponíveis
curl http://localhost:7100/mcp/tools/list | jq

# Testar tool call
curl -X POST http://localhost:7100/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"params":{"name":"get_config","arguments":{}}}'
```

---

## Performance & Scaling

### Local Development
- `docker-compose up` 
- Todos os 26 MCPs em um Docker daemon
- ~500MB RAM total

### Production (Kubernetes)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: config-mcp
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: config-mcp
        image: your-registry/config-mcp:latest
        ports:
        - containerPort: 7100
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "500m"
```

---

## Referências

- FastAPI: https://fastapi.tiangolo.com/
- Uvicorn: https://www.uvicorn.org/
- Docker Compose: https://docs.docker.com/compose/
- MCP Spec: https://modelcontextprotocol.io/

---

**Status:** ✅ Novo design pronto para implementação
**Próximo passo:** Converter todos os 26 MCPs para FastAPI + Docker
