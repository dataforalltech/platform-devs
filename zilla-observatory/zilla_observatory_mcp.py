#!/usr/bin/env python3
"""
zilla-observatory-mcp - Zilla Observatory & Monitoring MCP
Port: 7210
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logs_dir = os.path.join(os.path.expanduser('~'), '.platform', 'logs')
os.makedirs(logs_dir, exist_ok=True)

class PostgresStore:
    def __init__(self, service_name: str = "zilla-observatory"):
        self.service_name = service_name
        self.conn_params = {
            'host': os.getenv('POSTGRES_HOST', 'claude-dev'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'user': os.getenv('POSTGRES_USER', 'postgres'),
            'password': os.getenv('POSTGRES_PASSWORD', 'postgres_password_local_dev'),
            'database': os.getenv('POSTGRES_DB', 'app'),
        }
        self.log_file = os.path.join(logs_dir, f'{service_name}.log')
        self._test_connection()

    def _test_connection(self):
        try:
            conn = psycopg2.connect(**self.conn_params)
            conn.close()
        except Exception as e:
            raise RuntimeError(f'PostgreSQL connection failed: {e}')

    def _get_connection(self):
        return psycopg2.connect(**self.conn_params)

    def execute(self, query: str, params: List[Any] = None):
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(query, params or [])
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    def query(self, query: str, params: List[Any] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params or [])
            return cur.fetchall()
        except Exception as e:
            raise
        finally:
            conn.close()

class ZillaObservatoryStore:
    def __init__(self):
        self.db = PostgresStore('zilla-observatory')

    def list_metrics(self, zilla_name: Optional[str] = None, metric_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if zilla_name and metric_type:
            return self.db.query('SELECT * FROM metrics WHERE zilla_name = %s AND metric_type = %s ORDER BY recorded_at DESC', [zilla_name, metric_type])
        elif zilla_name:
            return self.db.query('SELECT * FROM metrics WHERE zilla_name = %s ORDER BY recorded_at DESC', [zilla_name])
        return self.db.query('SELECT * FROM metrics ORDER BY recorded_at DESC')

    def create_metric(self, zilla_name: str, metric_type: str, metric_value: Optional[float] = None, tags: Optional[Dict] = None) -> Dict[str, Any]:
        metric_id = f'metric_{uuid4().hex[:12]}'
        now = datetime.now().isoformat()

        self.db.execute(
            'INSERT INTO metrics (id, zilla_name, metric_type, metric_value, tags, recorded_at) VALUES (%s, %s, %s, %s, %s, %s)',
            [metric_id, zilla_name, metric_type, metric_value, json.dumps(tags) if tags else None, now]
        )

        return {'id': metric_id, 'zilla_name': zilla_name, 'metric_type': metric_type, 'metric_value': metric_value, 'recorded_at': now}

    def list_dashboards(self) -> List[Dict[str, Any]]:
        return self.db.query('SELECT * FROM dashboards ORDER BY created_at DESC')

    def create_dashboard(self, name: str, config: Optional[Dict] = None) -> Dict[str, Any]:
        dashboard_id = f'dash_{uuid4().hex[:12]}'
        now = datetime.now().isoformat()

        self.db.execute(
            'INSERT INTO dashboards (id, name, config, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)',
            [dashboard_id, name, json.dumps(config) if config else None, now, now]
        )

        return {'id': dashboard_id, 'name': name, 'config': config, 'created_at': now}

    def list_alerts(self, enabled: Optional[bool] = None) -> List[Dict[str, Any]]:
        if enabled is not None:
            return self.db.query('SELECT * FROM alerts WHERE enabled = %s ORDER BY created_at DESC', [enabled])
        return self.db.query('SELECT * FROM alerts ORDER BY created_at DESC')

    def create_alert(self, name: str, condition: Optional[str] = None, enabled: bool = True) -> Dict[str, Any]:
        alert_id = f'alert_{uuid4().hex[:12]}'
        now = datetime.now().isoformat()

        self.db.execute(
            'INSERT INTO alerts (id, name, condition, enabled, created_at) VALUES (%s, %s, %s, %s, %s)',
            [alert_id, name, condition, enabled, now]
        )

        return {'id': alert_id, 'name': name, 'condition': condition, 'enabled': enabled, 'created_at': now}

app = FastAPI(title="zilla-observatory-mcp", version="1.0.0")
store = ZillaObservatoryStore()

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)

class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

TOOLS = {
    'list_metrics': {'name': 'list_metrics', 'description': 'List metrics', 'inputSchema': {'type': 'object'}},
    'list_dashboards': {'name': 'list_dashboards', 'description': 'List dashboards', 'inputSchema': {'type': 'object'}},
    'list_alerts': {'name': 'list_alerts', 'description': 'List alerts', 'inputSchema': {'type': 'object'}},
}

@app.post("/mcp/initialize")
async def init(r: MCPRequest) -> MCPResponse:
    return MCPResponse(id=r.id, result={'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'zilla-observatory-mcp'}})

@app.post("/mcp/tools/list")
async def list_tools(r: MCPRequest) -> MCPResponse:
    return MCPResponse(id=r.id, result={'tools': list(TOOLS.values())})

@app.post("/mcp/tools/call")
async def call_tool(r: MCPRequest) -> MCPResponse:
    try:
        args = r.params.get('arguments', {})
        if r.params.get('name') == 'list_metrics':
            result = store.list_metrics(args.get('zilla_name'), args.get('metric_type'))
        elif r.params.get('name') == 'list_dashboards':
            result = store.list_dashboards()
        elif r.params.get('name') == 'list_alerts':
            result = store.list_alerts(args.get('enabled'))
        else:
            return MCPResponse(id=r.id, error={'code': -32601, 'message': 'Unknown tool'})
        return MCPResponse(id=r.id, result={'content': [{'type': 'text', 'text': json.dumps(result)}]})
    except Exception as e:
        return MCPResponse(id=r.id, error={'code': -32603, 'message': str(e)})

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7210))
    uvicorn.run(app, host="0.0.0.0", port=port)
