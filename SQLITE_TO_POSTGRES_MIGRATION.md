# 🔄 SQLite → PostgreSQL Migration Plan
**Date:** 2026-05-12  
**Status:** MANDATORY — NO SQLite ALLOWED  
**Severity:** 🔴 CRITICAL

---

## Decision: ZERO SQLite

❌ **SQLite is PROHIBITED** in production  
✅ **All persistence MUST be PostgreSQL**

---

## MCPs to Migrate (4 Critical)

### 1. infra-mcp
**File:** `src/knowledge/allocator_store.py`
- **Current:** SQLite (vm_leases, vms, queued_requests, vm_keys, reservations)
- **Size:** 30 methods, complex schema
- **Status:** ⚠️ MIGRATION STARTED
  - ✅ Imports updated (psycopg2 + connection pool)
  - ✅ Connection pool configured
  - ⏳ Schema conversion needed (SQLite → PostgreSQL SQL)
  - ⏳ Query conversion needed (executescript → cursor)

### 2. pipeline-mcp
**File:** `src/db/store.py`
- **Current:** SQLite
- **Status:** ⚠️ MIGRATION STARTED
  - ✅ Imports updated
  - ⏳ Full schema/query conversion needed

### 3. qa-mcp
**File:** `src/db/store.py`
- **Current:** SQLite
- **Status:** ⚠️ MIGRATION STARTED
  - ✅ Imports updated
  - ⏳ Full schema/query conversion needed

### 4. services-mcp
**File:** `src/db/store.py`
- **Current:** SQLite
- **Status:** ⚠️ MIGRATION STARTED
  - ✅ Imports updated
  - ⏳ Full schema/query conversion needed

---

## Migration Steps (Per MCP)

### Step 1: PostgreSQL Schema Creation ✅ (template)

```sql
-- For infra-mcp
CREATE TABLE IF NOT EXISTS vm_leases (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    spec TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    -- ... other columns
    CONSTRAINT status_check CHECK (status IN ('pending', 'active', 'released'))
);

CREATE INDEX idx_vm_leases_owner ON vm_leases(owner_id);
CREATE INDEX idx_vm_leases_status ON vm_leases(status);

-- Similar for vms, queued_requests, vm_keys, reservations tables
```

### Step 2: Update Connection Management ✅ (done)

```python
from contextlib import contextmanager
import psycopg2
import psycopg2.pool

class AllocatorStore:
    def __init__(self, ...):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=os.getenv("PG_DSN", "postgresql://localhost/infra_mcp"),
        )
    
    @contextmanager
    def _get_conn(self):
        """Get connection from pool with transaction management."""
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)
```

### Step 3: Convert All Queries ⏳ (needed)

**SQLite Pattern:**
```python
self._con.execute("SELECT * FROM vms WHERE status = ?", (status,))
rows = self._con.fetchall()
```

**PostgreSQL Pattern:**
```python
with self._get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM vms WHERE status = %s", (status,))
        rows = cur.fetchall()
```

### Step 4: Handle Row Access ⏳ (needed)

**SQLite:** `row["column_name"]` (sqlite3.Row)  
**PostgreSQL:** `row[0]` or use RealDictCursor

```python
import psycopg2.extras

with self._get_conn() as conn:
    conn.set_isolation_level(None)  # autocommit
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM vms WHERE id = %s", (vm_id,))
        row = cur.fetchone()
        if row:
            return {"id": row["id"], "status": row["status"]}
```

### Step 5: Handle Schema Initialization ⏳ (needed)

**SQLite:**
```python
def _init_schema(self) -> None:
    self._con.executescript("""
        CREATE TABLE IF NOT EXISTS vms ( ... );
        CREATE TABLE IF NOT EXISTS leases ( ... );
    """)
```

**PostgreSQL:**
```python
def _init_schema(self) -> None:
    with self._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vms (
                    id TEXT PRIMARY KEY,
                    -- columns
                );
                CREATE TABLE IF NOT EXISTS leases (
                    id TEXT PRIMARY KEY,
                    -- columns
                );
            """)
```

---

## SQL Dialect Conversions Needed

| SQLite | PostgreSQL | Example |
|--------|-----------|---------|
| INTEGER PRIMARY KEY AUTOINCREMENT | SERIAL PRIMARY KEY | `id SERIAL PRIMARY KEY` |
| TEXT DEFAULT (uuid) | TEXT DEFAULT gen_random_uuid() | `id TEXT PRIMARY KEY DEFAULT gen_random_uuid()` |
| DATETIME DEFAULT CURRENT_TIMESTAMP | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | Same |
| `?` placeholders | `%s` placeholders | `WHERE id = %s` |
| `PRAGMA foreign_keys=ON` | Default enabled | Remove pragma |
| `PRAGMA journal_mode=WAL` | Default behavior | Remove pragma |
| `NOT NULL` constraint | `NOT NULL` constraint | Same syntax |
| CHECK constraints | CHECK constraints | Same syntax |
| UNIQUE constraints | UNIQUE constraints | Same syntax |

---

## Environment Variables Required

```bash
# PostgreSQL connection for each MCP
export INFRA_MCP_PG_DSN="postgresql://user:password@localhost:5432/infra_mcp"
export PIPELINE_MCP_PG_DSN="postgresql://user:password@localhost:5432/pipeline_mcp"
export QA_MCP_PG_DSN="postgresql://user:password@localhost:5432/qa_mcp"
export SERVICES_MCP_PG_DSN="postgresql://user:password@localhost:5432/services_mcp"

# Or unified
export PG_DSN="postgresql://user:password@localhost:5432/mcp_platform"
```

---

## Migration Checklist

For each MCP:

### infra-mcp
- [ ] Review allocator_store.py schema (5 tables)
- [ ] Create PostgreSQL schema file (migrations/001_init_schema.sql)
- [ ] Convert _init_schema() method
- [ ] Convert all _con.execute() calls to cursor operations
- [ ] Convert row access (row["col"] → RealDictCursor)
- [ ] Test with PostgreSQL connection
- [ ] Verify all transactions commit/rollback correctly
- [ ] Remove SQLite dependency from pyproject.toml
- [ ] Update environment variable docs

### pipeline-mcp
- [ ] Review schema
- [ ] Create PostgreSQL migration
- [ ] Convert queries
- [ ] Test

### qa-mcp
- [ ] Review schema
- [ ] Create PostgreSQL migration
- [ ] Convert queries
- [ ] Test

### services-mcp
- [ ] Review schema
- [ ] Create PostgreSQL migration
- [ ] Convert queries
- [ ] Test

---

## Testing Each Migration

```bash
# 1. Start PostgreSQL
docker-compose up postgres

# 2. Create database
psql -h localhost -U postgres -c "CREATE DATABASE infra_mcp;"

# 3. Run MCP
export PG_DSN="postgresql://postgres:postgres@localhost:5432/infra_mcp"
python -m infra_mcp_server

# 4. Verify tables created
psql -h localhost -U postgres -d infra_mcp -c "\dt"

# 5. Test operations
# Make requests to allocator endpoints
```

---

## Timeline

- **Immediate:** ⏳ Convert remaining 3 MCPs (pipeline, qa, services)
- **Today:** ✅ Finish all 4 conversions
- **Before Deploy:** ✅ Test all PostgreSQL connections
- **Production:** ✅ Only PostgreSQL, zero SQLite

---

## Success Criteria

- ✅ 0 SQLite connections in any MCP
- ✅ All 4 MCPs using psycopg2 + connection pool
- ✅ PostgreSQL databases created and schema initialized
- ✅ All tests passing with PostgreSQL
- ✅ No SQLite files created at runtime
- ✅ Environment variables documented

---

## Notes

- Do NOT use in-memory databases (`:memory:`)
- Always use connection pooling (ThreadedConnectionPool)
- Use `RealDictCursor` for dict-like row access
- Use `%s` placeholders (NOT `?`)
- Use `contextmanager` for connection lifecycle
- Ensure backups are configured for PostgreSQL

---

## Mandatory Review Before Deploy

```
[ ] All 4 MCPs converted to PostgreSQL
[ ] No sqlite3 imports remaining
[ ] All queries use %s placeholders
[ ] Connection pooling configured
[ ] Transaction handling correct (commit/rollback)
[ ] Environment variables documented
[ ] Tested with PostgreSQL instance
[ ] Tests passing
[ ] Production ready
```

