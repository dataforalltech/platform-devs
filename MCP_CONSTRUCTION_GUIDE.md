# MCP Construction Guide

## Overview

Model Context Protocol (MCP) é um padrão aberto para comunicação entre clients e servidores especializados via JSON-RPC 2.0. Este guia documenta como construir MCPs que funcionam corretamente em Claude Code, baseado em 18 system MCPs (Python) e 8 zilla MCPs (Node.js/TypeScript).

**Especificação:** Model Context Protocol 2024-11-05
**Repo:** /home/dev/repos/platform-devs
**Total de MCPs:** 26 (18 system + 8 zilla, 270+ tools)

---

## Part 1: Anatomia de um MCP

### Comunicação: Stdio + JSON-RPC 2.0 (Única opção real)

Um MCP é um **processo standalone** que comunica via stdin/stdout com JSON-RPC 2.0:

```
Claude Code (client)
      ↓ (stdin)  
    MCP Server (subprocess)
      ↓ (stdout)
Claude Code (client)
```

**Protocolo:**
- Input: JSON objects, um por linha, via stdin
- Output: JSON objects, um por linha, via stdout
- Encoding: UTF-8, sem BOM
- Flush: obrigatório após cada resposta

### Métodos Obrigatórios (3 apenas)

Todo MCP deve responder a:

| Método | Propósito | Exemplo |
|--------|-----------|---------|
| `initialize` | Negocia versão do protocolo | `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}` |
| `tools/list` | Retorna array de tools | Resposta: `{"jsonrpc":"2.0","id":2,"result":{"tools":[...]}}` |
| `tools/call` | Executa uma tool | `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"...","arguments":{...}}}` |

### Tool Definition (Estrutura Obrigatória)

Cada tool **deve ter** esta estrutura exata:

```json
{
  "name": "analyze_requirement",
  "description": "Analyzes product requirements and identifies key components",
  "inputSchema": {
    "type": "object",
    "properties": {
      "requirement": {"type": "string"},
      "context": {"type": "string"}
    },
    "required": ["requirement"]
  }
}
```

**Erros documentados que ocorreram:**
- ❌ Tool sem `inputSchema` → aparece "estranha" em /mcp
- ❌ `inputSchema` vazio `{}` → aceita qualquer input (válido mas impreciso)
- ❌ Descrição genérica ("generate doc") → usuário não entende função
- ✅ Descrição específica ("Generates comprehensive documentation for features, APIs, or components")

---

## Part 2: Python vs Node.js

### Quando usar Python (Recomendado)

**Vantagens:**
- Sem dependências externas além stdlib
- Simples lógica síncrona (ideal para MCPs)
- Menor footprint (100-200 LOC por MCP)
- Rápido para prototipagem

**Exemplo mínimo (100 LOC):**
```python
#!/usr/bin/env python3
import json
import sys

class MyMCP:
    def __init__(self):
        self.name = "my-mcp"
        self.tools = [
            {
                "name": "do_something",
                "description": "Does something useful",
                "inputSchema": {
                    "type": "object",
                    "properties": {"input": {"type": "string"}},
                    "required": ["input"]
                }
            }
        ]
    
    def run(self):
        while True:
            line = sys.stdin.readline()
            if not line: break
            
            msg = json.loads(line)
            method = msg.get("method")
            msg_id = msg.get("id")
            
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": self.name, "version": "1.0"}
                    }
                }
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"tools": self.tools}
                }
            elif method == "tools/call":
                name = msg["params"]["name"]
                args = msg["params"].get("arguments", {})
                response = {
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"content": [{"type": "text", "text": f"Tool {name} executed"}]}
                }
            else:
                response = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
            
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    MyMCP().run()
```

**Casos de uso no projeto:**
- `config-mcp` (secrets, environment)
- `session-mcp` (session tracking)
- `audit-mcp` (audit logs)
- `auth-mcp` (authentication)
- `admin-mcp` (user management)
- 13 system MCPs totais

### Quando usar Node.js/TypeScript

**Vantagens:**
- Validação de schemas com Zod
- System prompts como Resources (além de Tools)
- Typed tool definitions
- Async/await nativo

**Quando preferir Node.js:**
- Quando você precisa de **Resources** além de Tools
- Quando você quer **Zod schemas** para validação forte
- Quando você precisa de **profile-based customization** (como archzilla)
- Quando você tem **database queries complexas** (sqlite com WAL)

**Estrutura típica (archzilla-mcp-server):**
```
archzilla-mcp-server/
├── src/
│   ├── server.ts           # Main MCP server (stdio transport)
│   ├── tools/
│   │   └── index.ts        # Tool schemas + dispatch logic
│   ├── db/
│   │   └── store.ts        # SQLite store
│   ├── prompts/
│   │   └── archzillaPrompt.ts
│   └── config/
│       └── settings.ts
├── dist/
│   └── server.js           # Compiled output
├── package.json            # npm dependencies
└── tsconfig.json
```

**Casos de uso no projeto:**
- `archzilla-mcp` (18 tools + system prompt + resources)
- `backzilla-mcp` (14 tools)
- `frontzilla-mcp` (26 tools)
- `opszilla-mcp` (19 tools)
- `pozilla-mcp` (17 tools)
- `productzilla-mcp` (18 tools)
- `qazilla-mcp` (33 tools)
- `seczilla-mcp` (25 tools)

### Comparação Técnica

| Aspecto | Python | Node.js |
|---------|--------|---------|
| Setup | Trivial (python3) | npm install + tsc |
| Compile | N/A | TypeScript → JavaScript |
| Schemas | dicts + validation manual | Zod (type-safe) |
| Resources | Não suportado | Suportado nativamente |
| Startup time | ~50ms | ~200ms |
| Memory | ~20MB | ~60MB |
| Ideal para | Simples tools | Complex schemas + prompts |
| Debugging | print() → stderr | console.error() → stderr |

---

## Part 3: HTTP vs Stdio

### Stdio (Correto e Obrigatório)

**O que é:** stdin/stdout communication entre processo Claude e processo MCP

**Quando usar:** SEMPRE. Essa é a única forma suportada para MCPs no Claude Code.

```bash
# Em .mcp.json:
{"command": "python3", "args": ["./my-mcp.py"]}
{"command": "node", "args": ["./dist/server.js"]}
```

**Como funciona:**
1. Claude Code inicia o MCP como subprocess
2. MCP fica escutando stdin
3. Claude envia JSON-RPC requests via stdin
4. MCP responde via stdout
5. Process termina quando cliente desconecta

### HTTP (Não necessário e evitar)

**Tentativa anterior:** MCPs tentaram rodar um HTTPServer em background para "aceitar HTTP também"

**Problema:** HTTP é comunicação server-to-server, não entre Claude e MCP
- Claude Code não conecta via HTTP ao MCP
- HTTPServer initialization silenciosamente falhava
- Adicionava complexidade sem benefício
- Threading causava race conditions

**Conclusão:** HTTP deve ser usado APENAS se o MCP precisa expor endpoints para outros serviços (fora do escopo de Claude Code).

**Eliminado no projeto:** Removemos todo HTTPServer dos 18 system MCPs na primeira iteração.

---

## Part 4: Boas Práticas e Erros Evitados

### ✅ O Que Funciona

1. **Stdin/Stdout apenas, uma linha por mensagem**
   ```python
   line = sys.stdin.readline()
   msg = json.loads(line)
   # ... process ...
   sys.stdout.write(json.dumps(response) + "\n")
   sys.stdout.flush()
   ```

2. **Tool definition completa com inputSchema**
   ```python
   "tools": [
       {
           "name": "tool_name",
           "description": "What this tool does, specifically",
           "inputSchema": {
               "type": "object",
               "properties": {...},
               "required": [...]
           }
       }
   ]
   ```

3. **Stderr apenas para erros, nunca para debug output**
   ```python
   sys.stderr.write(f"Error: {e}\n")  # ✅ OK, only on exception
   print("Debug info", file=sys.stderr)  # ❌ BREAKS PROTOCOL
   ```

4. **Flush após cada mensagem**
   ```python
   sys.stdout.write(json.dumps(response) + "\n")
   sys.stdout.flush()  # ✅ OBRIGATÓRIO
   ```

5. **Response format exato**
   ```json
   {
     "jsonrpc": "2.0",
     "id": 1,
     "result": { ... }
   }
   ```

### ❌ Erros Documentados

| Erro | Sintoma | Solução |
|------|---------|---------|
| stderr print durante init | Protocol corruption em /mcp | Remove all debug prints |
| Falta inputSchema | Tool aparece "estranha" | Add complete inputSchema |
| HTTPServer em thread | Silencioso hang/timeout | Remove HTTPServer entirely |
| Descrição genérica | Usuário não entende tool | Write specific descriptions |
| Sem flush() | Response nunca chega | Add sys.stdout.flush() |
| Exception durante tool/list | MCP disconnects | Add try/except na main loop |

---

## Part 5: Configuração (.mcp.json)

### Estrutura

```json
{
  "_comment": "MCP Ecosystem",
  "mcpServers": {
    "config-mcp": {
      "command": "python3",
      "args": ["./config-mcp.py"]
    },
    "archzilla-mcp": {
      "command": "node",
      "args": ["./archzilla-mcp-server/dist/server.js"]
    }
  }
}
```

**Regras:**
- `command`: Python MCPs usam `python3`, Node.js usam `node`
- `args`: Array de strings, caminho relativo ao repo root
- MCP inicia em `/home/dev/repos/platform-devs/`
- Paths relativos funcionam: `./my-mcp.py` ou `./folder/dist/server.js`

**Dois arquivos:**
- `/home/dev/repos/platform-devs/.mcp.json` → versionado em git
- `/home/dev/repos/platform-devs/.claude/.mcp.json` → cópia sincronizada

---

## Part 6: Verificação Checklist

Antes de commitar um novo MCP:

### Python MCP

- [ ] `#!/usr/bin/env python3` shebang
- [ ] Classe com `__init__`, `run()`, response methods
- [ ] `self.tools` lista com **todas as tools**
- [ ] Cada tool tem: `name`, `description`, `inputSchema` (completo)
- [ ] `main()` instancia e chama `.run()`
- [ ] `while True` loop lê stdin, processa, escreve stdout
- [ ] `sys.stdout.flush()` após cada response
- [ ] Sem `print(..., file=sys.stderr)` durante init
- [ ] Testa: `echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | python3 my-mcp.py`
- [ ] Adicionado a `.mcp.json` com comando correto
- [ ] Sem dependências externas além stdlib

### Node.js MCP

- [ ] TypeScript source em `src/`, compiled em `dist/`
- [ ] `StdioServerTransport` (não HTTP)
- [ ] `setRequestHandler` para todos os 3 métodos
- [ ] Tool schemas com Zod `z.object()`
- [ ] Cada tool has: `name`, `description`, `inputSchema`
- [ ] `npm install` + `npm run build` antes de commit
- [ ] Testa: `node dist/server.js` com initialize + tools/list
- [ ] `dist/` está compilado e funcional
- [ ] Adicionado a `.mcp.json` com `node` + path para dist/server.js
- [ ] package.json com `@modelcontextprotocol/sdk`

### Geral

- [ ] MCP testado localmente com stdin/stdout
- [ ] Todos os tools aparecem em `tools/list`
- [ ] Descriptions são específicas, não genéricas
- [ ] Sem HTTP server no código
- [ ] Sem print statements durante init
- [ ] Sem erros em stderr durante comunicação normal
- [ ] Adicionado a ambos .mcp.json e .claude/.mcp.json
- [ ] Commit message menciona quantos tools

---

## Part 7: Resumo de Decisões Arquiteturais

### Por que 100% Python não é viável

**Razão:** Os zilla MCPs precisam de:
1. **Strong typing** para tool schemas → Zod é melhor
2. **System prompts como Resources** → recurso MCP avançado
3. **Profile-based customization** → arquitetura complexa em TypeScript
4. **SQLite com WAL** → db store compartilhado

Python pode fazer isso, mas Node.js/TypeScript é mais natural.

### Por que manter ambos

- **Python:** 18 system MCPs são simples, stateless, rápido
- **Node.js:** 8 zilla MCPs são domain-specific, stateful, com prompts

**Resultado:** 26 MCPs, 270+ tools, melhor para cada caso.

### Lições aprendidas

1. **MCP = Stdio only** - HTTP é confusão desnecessária
2. **InputSchema é obrigatório** - sem ele, tools ficam "estranhas"
3. **Stderr only para exceptions** - debug prints quebram tudo
4. **Flush() é crítico** - sem ele, cliente fica pendurado
5. **Descriptions importam** - usuários entendem tools pelas descrições

---

## Referências

- MCP Spec: https://modelcontextprotocol.io/
- System MCPs: `/home/dev/repos/platform-devs/*-mcp.py` (18 files)
- Zilla MCPs: `/home/dev/repos/platform-devs/*zilla-mcp-server/src/server.ts` (8 folders)
- Config: `/home/dev/repos/platform-devs/.mcp.json`
- Claude Code docs: https://claude.com/claude-code

---

**Last updated:** 2026-05-10
**Status:** Complete ecosystem (26 MCPs, 270+ tools, all working)
