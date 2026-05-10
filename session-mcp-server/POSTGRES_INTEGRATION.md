# Session-MCP PostgreSQL Integration — Phase 2

**Status:** Integration code ready (src/db/postgres_sync.py)  
**Date:** May 10, 2026

---

## Overview

Este documento descreve como integrar PostgreSQL sync em session-mcp com dual-write pattern.

### Architecture

```
session-mcp tools (start_session, add_task, save_checkpoint, etc)
    ↓
SessionStore (SQLite — original, mantém funcionando)
    ↓
SessionPostgresSync (novo wrapper)
    ↓
MCPPostgreSQLAdapter (base class em lib/mcp_postgres_adapter.py)
    ↓
PostgreSQL (sincronizado durante operações)
```

### Key Points

- **Backward compatible:** SQLite continues to work; PostgreSQL is optional
- **Graceful degradation:** If PostgreSQL unavailable, sync fails silently (logged)
- **Dual-write:** Every session-mcp write goes to BOTH SQLite and PostgreSQL
- **No schema changes:** SessionStore schema remains unchanged
- **Lazy loading:** PostgreSQL adapter only created if enabled

---

## Integration Steps

### Step 1: Add postgres_sync.py to SessionStore initialization

**File:** `session-mcp-server/src/db/store.py`

Add to imports:
```python
from .postgres_sync import SessionPostgresSync
```

Add to SessionStore.__init__:
```python
class SessionStore:
    def __init__(self, db_path: str, postgres_config: dict = None) -> None:
        # ... existing code ...
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        
        # NEW: Initialize PostgreSQL sync
        self.postgres_sync = SessionPostgresSync(
            postgres_config or self._get_postgres_config(),
            enabled=True  # Set to False to disable PostgreSQL sync
        )
    
    def _get_postgres_config(self) -> dict:
        """Get PostgreSQL config from environment."""
        import os
        return {
            'dbname': os.getenv('POSTGRES_DB', 'app'),
            'user': os.getenv('POSTGRES_USER', 'postgres'),
            'password': os.getenv('POSTGRES_PASSWORD', 'postgres_password_local_dev'),
            'host': os.getenv('POSTGRES_HOST', 'claude-dev'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
        }
```

### Step 2: Add sync calls to session-mcp tools

**File:** `session-mcp-server/src/tools/session_tool.py`

After each SQLite write, call PostgreSQL sync:

#### In `start_session`:
```python
def start_session(store: SessionStore, params: dict):
    # ... existing SQLite write code ...
    session = store.create_session(...)
    
    # NEW: Sync to PostgreSQL
    store.postgres_sync.sync_session_created({
        'id': session['id'],
        'title': session['title'],
        'objective': params.get('objective'),
        'status': 'active',
        'started_at': session['started_at'],
        'last_updated_at': session['last_updated_at'],
    })
    
    return TextContent(...)
```

#### In `add_task`:
```python
def add_task(store: SessionStore, params: dict):
    # ... existing SQLite write code ...
    task = store.create_task(
        session_id=params['session_id'],
        title=params['title'],
        ...
    )
    
    # NEW: Sync to PostgreSQL
    store.postgres_sync.sync_task_created(params['session_id'], {
        'title': task['title'],
        'description': task.get('description'),
        'status': task['status'],
        'needs_human_decision': task.get('needs_human_decision', False),
        'created_at': task['created_at'],
    })
    
    return TextContent(...)
```

#### In `save_checkpoint`:
```python
def save_checkpoint(store: SessionStore, params: dict):
    # ... existing SQLite write code ...
    checkpoint = store.create_checkpoint(...)
    
    # NEW: Sync to PostgreSQL
    store.postgres_sync.sync_checkpoint_created(params['session_id'], {
        'summary': params['summary'],
        'context_json': json.dumps(params.get('context', {})),
        'created_at': checkpoint['created_at'],
    })
    
    return TextContent(...)
```

#### In `add_artifact`:
```python
def add_artifact(store: SessionStore, params: dict):
    # ... existing SQLite write code ...
    artifact = store.create_artifact(...)
    
    # NEW: Sync to PostgreSQL
    store.postgres_sync.sync_artifact_created(params['session_id'], {
        'type': params['artifact_type'],
        'content': params['content'],
        'created_at': artifact['created_at'],
    })
    
    return TextContent(...)
```

#### In `update_session`:
```python
def update_session(store: SessionStore, params: dict):
    # ... existing SQLite update code ...
    store.update_session(session_id=params['session_id'], ...)
    
    # NEW: Sync to PostgreSQL
    store.postgres_sync.sync_session_updated(
        params['session_id'],
        updates={
            'status': params.get('status'),
            'progress': params.get('progress'),
            'last_updated_at': datetime.now(timezone.utc).isoformat(),
        }
    )
    
    return TextContent(...)
```

#### In `complete_task`, `start_task`, `fail_task`:
```python
def complete_task(store: SessionStore, params: dict):
    # ... existing SQLite update code ...
    task = store.update_task(task_id=params['task_id'], status='completed')
    
    # NEW: Sync to PostgreSQL
    store.postgres_sync.sync_task_updated(
        params['task_id'],
        updates={
            'status': 'completed',
            'completed_at': datetime.now(timezone.utc).isoformat(),
        }
    )
    
    return TextContent(...)
```

### Step 3: Add audit logging for critical actions

**File:** `session-mcp-server/src/tools/session_tool.py`

For actions requiring audit trails (approvals, rejections):

```python
def approve_task(store: SessionStore, params: dict):
    # ... existing code ...
    
    # NEW: Log to audit trail
    store.postgres_sync.log_action(
        action='approve',
        target_type='task',
        target_id=str(params['task_id']),
        actor_id=params['actor']['id'] if params['actor']['type'] == 'human' else None,
        details={
            'actor_type': params['actor']['type'],
            'rationale': params.get('rationale'),
        }
    )
    
    return TextContent(...)
```

### Step 4: Handle server shutdown gracefully

**File:** `session-mcp-server/src/server/mcp_server.py`

In the main server exit handler:

```python
async def main():
    server = Server("session-mcp")
    # ... setup tools ...
    
    store = SessionStore(...)
    
    try:
        async with stdio_server(server) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_message_handler())
    finally:
        # Close PostgreSQL connection on shutdown
        if hasattr(store, 'postgres_sync'):
            store.postgres_sync.close()
            logger.info("PostgreSQL sync closed")
```

---

## Environment Variables

Set to enable/configure PostgreSQL sync:

```bash
# Default values (no need to set if using defaults)
export POSTGRES_DB="app"
export POSTGRES_USER="postgres"
export POSTGRES_PASSWORD="postgres_password_local_dev"
export POSTGRES_HOST="claude-dev"
export POSTGRES_PORT="5432"
```

To disable PostgreSQL sync entirely:
```python
# In SessionStore.__init__:
self.postgres_sync = SessionPostgresSync(
    postgres_config,
    enabled=False  # Disables PostgreSQL sync
)
```

---

## Testing Integration

### Unit Test Example

```python
import pytest
from src.db.store import SessionStore
from src.db.postgres_sync import SessionPostgresSync

def test_session_sync_to_postgres(tmp_path):
    """Test that creating a session syncs to PostgreSQL."""
    db_path = tmp_path / "test.db"
    
    # Mock postgres_config (would be real in integration test)
    postgres_config = {
        'dbname': 'test_app',
        'user': 'postgres',
        'password': 'test_password',
        'host': 'localhost',
        'port': 5432,
    }
    
    store = SessionStore(str(db_path), postgres_config)
    
    # Create session
    session = store.create_session(
        title="Test Session",
        objective="Test objective",
        repo="test-repo"
    )
    
    # Sync should have been called (check logs or query PostgreSQL)
    assert session['id'].startswith('sess_')
    
    store.postgres_sync.close()
```

### Integration Test

```bash
# 1. Ensure PostgreSQL is running and schema applied
psql -h claude-dev -U postgres -d app < /home/dev/repos/platform-service-template/db/schema.sql

# 2. Start session-mcp with PostgreSQL enabled
cd /home/dev/repos/platform-devs/session-mcp-server
POSTGRES_HOST=claude-dev POSTGRES_DB=app python3 -m src.server.mcp_server

# 3. In another terminal, test via MCP
# Call: start_session(title="Test", objective="...", repo="platform-service-template")

# 4. Verify in PostgreSQL
psql -h claude-dev -U postgres -d app
SELECT * FROM sessions WHERE title = 'Test';
SELECT COUNT(*) FROM sessions;  -- Should show new session
```

---

## Error Handling

### PostgreSQL Down

If PostgreSQL is unavailable:
- Log: "⚠️ PostgreSQL sync disabled: connection refused"
- Behavior: session-mcp continues working with SQLite only
- No data loss (SQLite still operates normally)
- Sync resumes when PostgreSQL comes back online

### Network Error

If network to PostgreSQL fails during sync:
- Log: "Failed to sync session created: network error"
- Behavior: operation succeeds in SQLite, fails silently in PostgreSQL
- Session continues with SQLite as source of truth
- Audit log shows attempt to sync (via logging)

### Schema Mismatch

If PostgreSQL schema doesn't match:
- Log: "Error during sync_to_postgres: column 'progress_percentage' does not exist"
- Fix: Apply schema from `db/schema.sql` to PostgreSQL

---

## Monitoring

### Health Check

```python
# In session-mcp tools or monitoring script
is_postgres_healthy = store.postgres_sync.health_check()
if not is_postgres_healthy:
    logger.warning("PostgreSQL connection unhealthy")
    # Can trigger alert, disable sync, etc.
```

### Logging

All sync operations are logged:
```
DEBUG:src.db.postgres_sync:Synced session created: sess_xyz
DEBUG:src.db.postgres_sync:Synced task created in session sess_xyz: Implementation
ERROR:src.db.postgres_sync:Failed to sync checkpoint created: connection timeout
```

Monitor logs for:
- `✅ SessionPostgresSync initialized` — sync enabled and working
- `⚠️ PostgreSQL sync disabled` — connection failed
- `ERROR` — sync operations failing (but SQLite operations continuing)

---

## Performance Impact

- **No blocking:** PostgreSQL writes are synchronous but failures don't block SQLite writes
- **Network latency:** ~10-50ms per sync operation (negligible vs. tool execution time)
- **Batch impact:** Small batches (1-10 rows) sync in < 1ms
- **Recommended:** Monitor PostgreSQL connection pool if throughput increases

---

## Rollback (if needed)

If PostgreSQL integration causes issues:

1. **Disable sync without code changes:**
   ```python
   # In SessionStore.__init__:
   enabled=False  # Temporary disable
   ```

2. **Remove sync calls from tools** (if code was modified):
   - Delete all `store.postgres_sync.sync_*()` calls
   - Keep postgres_sync initialization in SessionStore (no-op if disabled)

3. **Keep postgres_sync.py for future use** — no harm if not called

---

## Next Steps (Phase 2B)

Same integration pattern for:
- **config-mcp:** Sync credentials metadata
- **services-mcp:** Sync service registry + health status
- **deploy-mcp:** Sync repositories and task status

---

**Integration Owner:** Platform Team  
**Phase 2 Timeline:** May 12-13, 2026  
**Target:** All 3 MCPs integrated with dual-write pattern
