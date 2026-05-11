# MCP Build Examples - Passo a Passo

Quick reference para criar um novo MCP do zero. Teste localmente antes de adicionar ao .mcp.json.

---

## Exemplo 1: MCP Simples em Python (10 min)

### Requisitos
- Python 3.7+
- Nenhuma dependência externa

### Passo 1: Criar arquivo

```bash
touch my-service-mcp.py
chmod +x my-service-mcp.py
```

### Passo 2: Estrutura base

```python
#!/usr/bin/env python3
"""My Service MCP with 3 tools."""
import json
import sys

class MyServiceMCP:
    def __init__(self):
        self.name = "my-service-mcp"
        self.tools = [
            {
                "name": "get_user",
                "description": "Retrieves user information by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"}
                    },
                    "required": ["user_id"]
                }
            },
            {
                "name": "create_user",
                "description": "Creates a new user with name and email",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"}
                    },
                    "required": ["name", "email"]
                }
            },
            {
                "name": "list_users",
                "description": "Lists all users with optional filtering",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"}
                    },
                    "required": []
                }
            }
        ]

    def initialize(self, msg_id: int) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": self.name,
                    "version": "1.0"
                }
            }
        }

    def list_tools(self, msg_id: int) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": self.tools}
        }

    def call_tool(self, msg_id: int, tool_name: str, arguments: dict) -> dict:
        # Aqui vai a lógica real de cada tool
        if tool_name == "get_user":
            user_id = arguments.get("user_id")
            result_text = f"User {user_id}: {{id: {user_id}, name: John, email: john@example.com}}"
        elif tool_name == "create_user":
            name = arguments.get("name")
            email = arguments.get("email")
            result_text = f"Created user: {{name: {name}, email: {email}}}"
        elif tool_name == "list_users":
            limit = arguments.get("limit", 10)
            result_text = f"Listed {limit} users"
        else:
            result_text = f"Unknown tool: {tool_name}"

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": result_text
                    }
                ]
            }
        }

    def run(self):
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                msg = json.loads(line)
                msg_id = msg.get("id", 0)
                method = msg.get("method", "")
                params = msg.get("params", {})

                if method == "initialize":
                    response = self.initialize(msg_id)
                elif method == "tools/list":
                    response = self.list_tools(msg_id)
                elif method == "tools/call":
                    tool_name = params.get("name", "")
                    arguments = params.get("arguments", {})
                    response = self.call_tool(msg_id, tool_name, arguments)
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {}
                    }

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                sys.stderr.write(f"JSONDecodeError: {e}\n")
            except Exception as e:
                sys.stderr.write(f"Error: {e}\n")


if __name__ == "__main__":
    mcp = MyServiceMCP()
    mcp.run()
```

### Passo 3: Testar localmente

```bash
# Terminal 1: Iniciar MCP
python3 my-service-mcp.py

# Terminal 2: Enviar requests
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | nc localhost 9999

# Ou usando pipe direto:
(echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'; sleep 0.1; echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}') | python3 my-service-mcp.py
```

**Output esperado:**
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"my-service-mcp","version":"1.0"}}}
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"get_user",...},...]}}
```

### Passo 4: Adicionar ao .mcp.json

```json
{
  "mcpServers": {
    "my-service-mcp": {"command": "python3", "args": ["./my-service-mcp.py"]}
  }
}
```

### Passo 5: Commit

```bash
git add my-service-mcp.py .mcp.json .claude/.mcp.json
git commit -m "feat: Add my-service-mcp with 3 tools (get_user, create_user, list_users)"
```

---

## Exemplo 2: MCP em Node.js/TypeScript (30 min)

### Requisitos
- Node.js 18+
- TypeScript
- `@modelcontextprotocol/sdk`

### Passo 1: Estrutura

```bash
mkdir my-domain-mcp-server
cd my-domain-mcp-server

npm init -y
npm install @modelcontextprotocol/sdk zod
npm install -D typescript @types/node

touch tsconfig.json src/server.ts src/tools/index.ts
```

### Passo 2: tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ES2020",
    "lib": ["ES2020"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "moduleResolution": "node"
  },
  "include": ["src/**/*"]
}
```

### Passo 3: package.json

```json
{
  "name": "my-domain-mcp-server",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "build": "tsc",
    "start": "node dist/server.js",
    "dev": "tsc && node dist/server.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "latest",
    "zod": "^3.22.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "typescript": "^5.0.0"
  }
}
```

### Passo 4: src/tools/index.ts

```typescript
import { z } from 'zod';

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: z.ZodSchema;
}

const getUserSchema = z.object({
  user_id: z.string(),
});

const createUserSchema = z.object({
  name: z.string(),
  email: z.string().email(),
});

export const TOOL_SCHEMAS: Record<string, ToolSchema> = {
  get_user: {
    name: 'get_user',
    description: 'Retrieves user information by ID',
    inputSchema: getUserSchema,
  },
  create_user: {
    name: 'create_user',
    description: 'Creates a new user with name and email',
    inputSchema: createUserSchema,
  },
  list_users: {
    name: 'list_users',
    description: 'Lists all users with optional filtering',
    inputSchema: z.object({
      limit: z.number().optional(),
      offset: z.number().optional(),
    }),
  },
};

export async function dispatch(
  toolName: string,
  args: unknown
): Promise<string> {
  const schema = TOOL_SCHEMAS[toolName];
  if (!schema) {
    throw new Error(`Unknown tool: ${toolName}`);
  }

  const validated = schema.inputSchema.parse(args);

  if (toolName === 'get_user') {
    const { user_id } = validated as z.infer<typeof getUserSchema>;
    return JSON.stringify({
      id: user_id,
      name: 'John',
      email: 'john@example.com',
    });
  } else if (toolName === 'create_user') {
    const { name, email } = validated as z.infer<typeof createUserSchema>;
    return JSON.stringify({ name, email, created: true });
  } else if (toolName === 'list_users') {
    const limit = (validated as any).limit || 10;
    return JSON.stringify({ users: [], total: 0, limit });
  }

  throw new Error(`No implementation for tool: ${toolName}`);
}
```

### Passo 5: src/server.ts

```typescript
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
  Tool,
} from '@modelcontextprotocol/sdk/types.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { TOOL_SCHEMAS, dispatch } from './tools/index.js';

async function handleListTools(): Promise<{ tools: Tool[] }> {
  const tools = Object.values(TOOL_SCHEMAS).map((schema) => ({
    name: schema.name,
    description: schema.description,
    inputSchema: {
      type: 'object' as const,
      properties: {},
    },
  }));
  return { tools };
}

async function handleCallTool(request: {
  params: { name: string; arguments?: Record<string, unknown> };
}): Promise<{ content: Array<{ type: string; text: string }> }> {
  const { name, arguments: args = {} } = request.params;
  const result = await dispatch(name, args);

  return {
    content: [
      {
        type: 'text',
        text: result,
      },
    ],
  };
}

async function main() {
  const transport = new StdioServerTransport();
  const server = new Server(
    {
      name: 'my-domain-mcp-server',
      version: '0.1.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  server.setRequestHandler(ListToolsRequestSchema, handleListTools);
  server.setRequestHandler(CallToolRequestSchema, handleCallTool);

  await server.connect(transport);
}

main().catch(console.error);
```

### Passo 6: Build e test

```bash
npm run build

# Test
(echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'; sleep 0.1; echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}') | node dist/server.js
```

### Passo 7: Adicionar ao .mcp.json

```json
{
  "mcpServers": {
    "my-domain-mcp": {"command": "node", "args": ["./my-domain-mcp-server/dist/server.js"]}
  }
}
```

### Passo 8: Commit

```bash
git add my-domain-mcp-server/ .mcp.json .claude/.mcp.json
git commit -m "feat: Add my-domain-mcp-server with 3 tools (get_user, create_user, list_users)"
```

---

## Checklist de Qualidade

### Python MCP

```bash
# 1. Teste stdin/stdout
(echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'; sleep 0.1; echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}') | python3 my-mcp.py | jq

# 2. Verifique tool count
python3 my-mcp.py | jq '.result.tools | length'

# 3. Teste uma tool
echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"tool_name","arguments":{}}}' | python3 my-mcp.py | jq

# 4. Sem print() debug statements
grep -n 'print(' my-mcp.py | grep -v '#'
```

### Node.js MCP

```bash
# 1. Compile sem erros
npm run build

# 2. Teste
(echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'; sleep 0.1; echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}') | node dist/server.js | jq

# 3. Tool count
node dist/server.js | jq '.result.tools | length'

# 4. Sem TypeScript errors
npx tsc --noEmit
```

---

## Troubleshooting

### "MCP appears offline in Claude Code"

1. **Test locally first:**
   ```bash
   python3 my-mcp.py << 'EOF'
   {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
   EOF
   ```

2. **Check stderr output:** Se vê mensagens em stderr, MCP quebrou o protocolo
   - Remova todos `print(..., file=sys.stderr)` que não sejam exceptions
   - Remova todos `console.error()` que não sejam exceptions

3. **Check tool definitions:**
   ```bash
   python3 my-mcp.py << 'EOF'
   {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
   {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
   EOF
   ```
   Cada tool deve ter `name`, `description`, `inputSchema`

4. **Reload MCPs in Claude Code:** Use `/mcp` command to refresh

### "Tools appear strange or incomplete"

- Falta `inputSchema` nas tool definitions
- `inputSchema` está vazio `{}`
- Descrição é genérica ("generate doc")

**Fix:**
```python
"inputSchema": {
    "type": "object",
    "properties": {
        "param1": {"type": "string"},
        "param2": {"type": "number"}
    },
    "required": ["param1"]
}
```

---

**Template final:** Copie exemplo 1 ou 2 acima e customize para seu caso.
