#!/usr/bin/env python3
"""
cross-zilla-validators-mcp - Cross-Zilla Validators MCP
Port: 7209
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
    def __init__(self, service_name: str = "cross-zilla-validators"):
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

class CrossZillaValidatorsStore:
    def __init__(self):
        self.db = PostgresStore('cross-zilla-validators')

    def list_validation_results(self, validator_name: Optional[str] = None) -> List[Dict[str, Any]]:
        if validator_name:
            return self.db.query('SELECT * FROM validation_results WHERE validator_name = %s ORDER BY created_at DESC', [validator_name])
        return self.db.query('SELECT * FROM validation_results ORDER BY created_at DESC')

    def create_validation_result(self, validator_name: str, target_id: Optional[str], target_type: Optional[str], result_status: str, details: Optional[Dict] = None) -> Dict[str, Any]:
        result_id = f'vr_{uuid4().hex[:12]}'
        now = datetime.now().isoformat()

        self.db.execute(
            'INSERT INTO validation_results (id, validator_name, target_id, target_type, result_status, details, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)',
            [result_id, validator_name, target_id, target_type, result_status, json.dumps(details) if details else None, now]
        )

        return {'id': result_id, 'validator_name': validator_name, 'target_id': target_id, 'target_type': target_type, 'result_status': result_status, 'created_at': now}

    def list_validator_rules(self, validator_name: Optional[str] = None) -> List[Dict[str, Any]]:
        if validator_name:
            return self.db.query('SELECT * FROM validator_rules WHERE validator_name = %s ORDER BY created_at DESC', [validator_name])
        return self.db.query('SELECT * FROM validator_rules ORDER BY created_at DESC')

    def get_validation_statistics(self, validator_name: Optional[str] = None) -> List[Dict[str, Any]]:
        if validator_name:
            return self.db.query('SELECT validator_name, COUNT(*) as count FROM validation_results WHERE validator_name = %s GROUP BY validator_name', [validator_name])
        return self.db.query('SELECT validator_name, COUNT(*) as count FROM validation_results GROUP BY validator_name')

app = FastAPI(title="cross-zilla-validators-mcp", version="1.0.0")
store = CrossZillaValidatorsStore()

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
    'list_validation_results': {'name': 'list_validation_results', 'description': 'List validation results', 'inputSchema': {'type': 'object'}},
    'get_validation_statistics': {'name': 'get_validation_statistics', 'description': 'Get validation statistics', 'inputSchema': {'type': 'object'}},
}

@app.post("/mcp/initialize")
async def init(r: MCPRequest) -> MCPResponse:
    return MCPResponse(id=r.id, result={'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'cross-zilla-validators-mcp'}})

@app.post("/mcp/tools/list")
async def list_tools(r: MCPRequest) -> MCPResponse:
    return MCPResponse(id=r.id, result={'tools': list(TOOLS.values())})

@app.post("/mcp/tools/call")
async def call_tool(r: MCPRequest) -> MCPResponse:
    try:
        if r.params.get('name') == 'list_validation_results':
            result = store.list_validation_results(r.params.get('arguments', {}).get('validator_name'))
        elif r.params.get('name') == 'get_validation_statistics':
            result = store.get_validation_statistics(r.params.get('arguments', {}).get('validator_name'))
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
    port = int(os.environ.get("PORT", 7209))
    uvicorn.run(app, host="0.0.0.0", port=port)
