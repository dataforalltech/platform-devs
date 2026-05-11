# Zillas Python Stack — 100% PostgreSQL Primary

**Status**: ✅ Migração Completa (SQLite → Python + PostgreSQL)  
**Data**: 2026-05-11  
**Stack**: Python 3.10+ | FastAPI | PostgreSQL | psycopg2

---

## Overview

Todos os 10 Zilla MCPs foram reescritos em Python e usam **PostgreSQL como fonte única de verdade** (sem SQLite).

### Zillas

1. **qazilla-mcp-server** (Port 7201) — Quality Assurance
2. **seczilla-mcp-server** (Port 7202) — Security & Threat Modeling
3. **archzilla-mcp-server** (Port 7203) — Architecture & ADRs
4. **backzilla-mcp-server** (Port 7204) — Backend APIs
5. **frontzilla-pixelfera-mcp-server** (Port 7205) — Frontend Components
6. **opszilla-mcp-server** (Port 7206) — Operations & DevOps
7. **pozilla-mcp-server** (Port 7207) — Product Ownership
8. **productzilla-mcp-server** (Port 7208) — Product Management
9. **cross-zilla-validators** (Port 7209) — Cross-Zilla Validators
10. **zilla-observatory** (Port 7210) — Monitoring & Dashboards

---

## Arquitetura

### Estrutura de Arquivo

```
{zilla}-mcp-server/
├── {zilla}_mcp.py          # FastAPI MCP service
├── requirements.txt         # Dependencies (shared)
└── README.md               # Zilla-specific docs
```

### Stack

- **Framework**: FastAPI (HTTP service com protocolo MCP)
- **Database**: PostgreSQL (conexão via psycopg2)
- **Logging**: Arquivo em `~/.platform/logs/{zilla}.log`
- **ID Generation**: UUID com prefixos tipados (e.g., `tp_`, `bug_`, `tc_`)
- **Timestamps**: ISO8601 (datetime.isoformat())

### Padrão de Código

Cada Zilla segue o mesmo padrão:

```python
class PostgresStore:
    """Generic store para PostgreSQL"""
    def execute(query, params)  # INSERT/UPDATE/DELETE
    def query(query, params)    # SELECT

class {ZillaName}Store:
    """Implementação específica do Zilla"""
    def list_{table}()
    def create_{model}(**kwargs)
    def get_validation_stats()  # Se aplicável

@app.post("/mcp/initialize")    # MCP Protocol
@app.post("/mcp/tools/list")
@app.post("/mcp/tools/call")
@app.get("/health")
```

---

## Setup & Execução

### 1. Instalar Dependências

```bash
pip install fastapi uvicorn psycopg2-binary pydantic
```

Ou usar requirements.txt compartilhado:

```bash
pip install -r /home/dev/repos/platform-devs/requirements-zillas.txt
```

### 2. Variáveis de Ambiente

```bash
export POSTGRES_HOST=claude-dev
export POSTGRES_PORT=5432
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres_password_local_dev
export POSTGRES_DB=app
```

### 3. Rodar um Zilla

```bash
cd /home/dev/repos/platform-devs/qazilla-mcp-server
python qazilla_mcp.py
# Server running on http://0.0.0.0:7201

# Ou com Uvicorn direto:
uvicorn qazilla_mcp:app --port 7201 --reload
```

### 4. Testar via MCP

```bash
curl -X POST http://localhost:7201/mcp/tools/list \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}'
```

---

## PostgreSQL Schema

Todas as tabelas foram criadas via DDL em `db/create_zilla_tables.sql`:

- 45 tabelas Zilla
- Índices em colunas de relacionamento
- TIMESTAMPTZ para timestamps
- JSONB para dados complexos (spec, config, items, etc.)

**Validação**:
```bash
python db/migrate_zillas_to_postgres.py --validate
```

---

## Migração de Dados (SQLite → PostgreSQL)

Dados existentes podem ser migrados:

```bash
python db/migrate_zillas_to_postgres.py
```

Flags:
- `--dry-run` — Mostrar o que seria migrado
- `--validate` — Verificar integridade pós-migração
- `--zilla qazilla` — Migrar apenas uma Zilla

---

## Logs

Cada Zilla gera logs em `~/.platform/logs/{zilla}.log`:

```
[2026-05-11T12:34:56.123456] ✅ PostgreSQL connected
[2026-05-11T12:34:57.234567] INFO: Tool list_test_plans called
[2026-05-11T12:34:57.345678] Query failed: relation "test_plans" does not exist
```

---

## Próximos Passos

1. **Teste de Integração**: Chamar cada Zilla via MCP
2. **Load Testing**: Validar performance com múltiplas conexões
3. **Health Checks**: Monitorar endpoints `/health`
4. **CI/CD**: Atualizar pipelines para rodar `python {zilla}_mcp.py`
5. **Documentação Zilla-específica**: README em cada pasta

---

## Removido

❌ **Node.js / TypeScript**
- Remover: `/src`, `tsconfig.json`, `package.json`, `dist/`

❌ **SQLite**
- Remover: `/tmp/*.db` (já feito)
- Remover: `better-sqlite3` (já feito)

❌ **Store.ts files**
- Remover: `src/db/store.ts` (mantê-los como referência em `.backup`)

---

## Referencias

- [MCP Protocol](https://modelcontextprotocol.io/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [psycopg2 Docs](https://www.psycopg.org/)
- [PostgreSQL JSON](https://www.postgresql.org/docs/current/datatype-json.html)

---

**Compatibilidade**: Python 3.10+  
**Última Atualização**: 2026-05-11  
**Stack**: 100% Python
