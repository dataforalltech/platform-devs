#!/usr/bin/env python3
"""
qazilla-mcp - Quality Assurance Zilla MCP
PostgreSQL-only storage (no SQLite)
Port: 7201
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from uuid import uuid4
from enum import Enum

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator

# ============================================================================
# Pydantic Input Validation Models (Security Fix: Input Validation)
# ============================================================================

class CreateTestPlanRequest(BaseModel):
    """Validated input for creating test plans"""
    title: str = Field(..., min_length=1, max_length=255, description="Test plan title")
    feature: str = Field(..., min_length=1, max_length=255, description="Feature being tested")
    scope: str = Field(..., min_length=1, max_length=1000, description="Test scope")
    objectives: str = Field(..., min_length=1, max_length=2000, description="Test objectives")
    status: str = Field(default="draft", description="Initial status")

    @validator("status")
    def validate_status(cls, v):
        if v not in ["draft", "ready", "in_progress", "completed", "failed"]:
            raise ValueError(f"Invalid status: {v}. Must be one of: draft, ready, in_progress, completed, failed")
        return v

class UpdateTestPlanRequest(BaseModel):
    """Validated input for updating test plans"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    feature: Optional[str] = Field(None, min_length=1, max_length=255)
    scope: Optional[str] = Field(None, min_length=1, max_length=1000)
    objectives: Optional[str] = Field(None, min_length=1, max_length=2000)
    status: Optional[str] = Field(None)

    @validator("status")
    def validate_status(cls, v):
        if v is not None and v not in ["draft", "ready", "in_progress", "completed", "failed"]:
            raise ValueError(f"Invalid status: {v}")
        return v

class CreateTestCaseRequest(BaseModel):
    """Validated input for creating test cases"""
    plan_id: str = Field(..., min_length=1, description="Parent test plan ID")
    title: str = Field(..., min_length=1, max_length=255, description="Test case title")
    type: str = Field(..., description="Test case type")
    steps: Optional[str] = Field(None, max_length=5000)
    expected_result: Optional[str] = Field(None, max_length=5000)

    @validator("type")
    def validate_type(cls, v):
        if v not in ["positive", "negative", "edge_case", "boundary", "performance"]:
            raise ValueError(f"Invalid type: {v}")
        return v

class CreateBugReportRequest(BaseModel):
    """Validated input for creating bug reports"""
    title: str = Field(..., min_length=1, max_length=255)
    severity: str = Field(..., description="Bug severity level")
    priority: str = Field(..., description="Bug priority level")
    steps_to_reproduce: str = Field(..., min_length=1, max_length=5000)
    expected: str = Field(..., min_length=1, max_length=2000)
    actual: str = Field(..., min_length=1, max_length=2000)
    environment: str = Field(..., min_length=1, max_length=500)

    @validator("severity")
    def validate_severity(cls, v):
        if v not in ["critical", "high", "medium", "low"]:
            raise ValueError(f"Invalid severity: {v}")
        return v

    @validator("priority")
    def validate_priority(cls, v):
        if v not in ["blocker", "high", "medium", "low", "trivial"]:
            raise ValueError(f"Invalid priority: {v}")
        return v

# ============================================================================
# Logging Setup
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logs_dir = os.path.join(os.path.expanduser('~'), '.platform', 'logs')
os.makedirs(logs_dir, exist_ok=True)

# ============================================================================
# Data Models (Dataclasses)
# ============================================================================

@dataclass
class TestPlan:
    id: str
    title: str
    feature: str
    scope: str
    objectives: str
    status: str
    created_at: str
    updated_at: str

@dataclass
class TestCase:
    id: str
    plan_id: Optional[str]
    title: str
    type: str
    steps: str
    expected_result: str
    status: str
    created_at: str

@dataclass
class TestScenario:
    id: str
    plan_id: Optional[str]
    title: str
    scenario: str
    tags: str
    created_at: str

@dataclass
class BugReport:
    id: str
    title: str
    severity: str
    priority: str
    steps_to_reproduce: str
    expected: str
    actual: str
    environment: str
    status: str
    created_at: str

@dataclass
class QualityGate:
    id: str
    name: str
    criteria: str
    threshold: Optional[float]
    status: str
    created_at: str
    updated_at: str

@dataclass
class TestResult:
    id: str
    plan_id: str
    status: str
    passed: Optional[int]
    failed: Optional[int]
    coverage: Optional[float]
    notes: Optional[str]
    recorded_at: str

@dataclass
class Checklist:
    id: str
    title: str
    items: Optional[Dict[str, Any]]
    status: str
    created_at: str

@dataclass
class QAExecution:
    id: str
    plan_id: Optional[str]
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str

# ============================================================================
# Database Connection Pool
# ============================================================================

class PostgresStore:
    def __init__(self, service_name: str = "qazilla"):
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
            self._log_info(f'✅ PostgreSQL connected')
        except Exception as e:
            self._log_error(f'❌ PostgreSQL connection failed: {e}')
            raise

    def _get_connection(self):
        return psycopg2.connect(**self.conn_params)

    def _log_info(self, msg: str):
        timestamp = datetime.now().isoformat()
        log_msg = f'[{timestamp}] ℹ️  {msg}'
        print(log_msg)
        with open(self.log_file, 'a') as f:
            f.write(f'[{timestamp}] INFO: {msg}\n')

    def _log_error(self, msg: str):
        timestamp = datetime.now().isoformat()
        log_msg = f'[{timestamp}] ❌ {msg}'
        print(log_msg, file=__import__('sys').stderr)
        with open(self.log_file, 'a') as f:
            f.write(f'[{timestamp}] ERROR: {msg}\n')

    def execute(self, query: str, params: List[Any] = None):
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(query, params or [])
            conn.commit()
        except Exception as e:
            conn.rollback()
            self._log_error(f'Execute failed: {e}')
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
            self._log_error(f'Query failed: {e}')
            raise
        finally:
            conn.close()

# ============================================================================
# QAZilla Store
# ============================================================================

class QAZillaStore:
    def __init__(self):
        self.db = PostgresStore('qazilla')

    # Test Plans
    def create_test_plan(self, title: str, feature: str, scope: str, objectives: str, status: str = 'draft') -> TestPlan:
        plan_id = f'tp_{uuid4().hex[:12]}'
        now = datetime.now().isoformat()

        self.db.execute(
            'INSERT INTO test_plans (id, title, feature, scope, objectives, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            [plan_id, title, feature, scope, objectives, status, now, now]
        )

        return TestPlan(id=plan_id, title=title, feature=feature, scope=scope, objectives=objectives, status=status, created_at=now, updated_at=now)

    def list_test_plans(self) -> List[TestPlan]:
        rows = self.db.query('SELECT * FROM test_plans ORDER BY created_at DESC')
        return [TestPlan(**row) for row in rows]

    def get_test_plan(self, plan_id: str) -> Optional[TestPlan]:
        rows = self.db.query('SELECT * FROM test_plans WHERE id = %s', [plan_id])
        return TestPlan(**rows[0]) if rows else None

    # Test Cases
    def create_test_case(self, plan_id: Optional[str], title: str, type: str, steps: str, expected_result: str, status: str = 'draft') -> TestCase:
        case_id = f'tc_{uuid4().hex[:12]}'
        now = datetime.now().isoformat()

        self.db.execute(
            'INSERT INTO test_cases (id, plan_id, title, type, steps, expected_result, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            [case_id, plan_id, title, type, steps, expected_result, status, now]
        )

        return TestCase(id=case_id, plan_id=plan_id, title=title, type=type, steps=steps, expected_result=expected_result, status=status, created_at=now)

    def list_test_cases(self, plan_id: Optional[str] = None) -> List[TestCase]:
        if plan_id:
            rows = self.db.query('SELECT * FROM test_cases WHERE plan_id = %s ORDER BY created_at DESC', [plan_id])
        else:
            rows = self.db.query('SELECT * FROM test_cases ORDER BY created_at DESC')
        return [TestCase(**row) for row in rows]

    # Bug Reports
    def create_bug_report(self, title: str, severity: str, priority: str, steps_to_reproduce: str, expected: str, actual: str, environment: str, status: str = 'open') -> BugReport:
        bug_id = f'bug_{uuid4().hex[:12]}'
        now = datetime.now().isoformat()

        self.db.execute(
            'INSERT INTO bug_reports (id, title, severity, priority, steps_to_reproduce, expected, actual, environment, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [bug_id, title, severity, priority, steps_to_reproduce, expected, actual, environment, status, now]
        )

        return BugReport(id=bug_id, title=title, severity=severity, priority=priority, steps_to_reproduce=steps_to_reproduce, expected=expected, actual=actual, environment=environment, status=status, created_at=now)

    def list_bug_reports(self) -> List[BugReport]:
        rows = self.db.query('SELECT * FROM bug_reports ORDER BY created_at DESC')
        return [BugReport(**row) for row in rows]

# ============================================================================
# FastAPI MCP Service
# ============================================================================

app = FastAPI(
    title="qazilla-mcp",
    version="1.0.0",
    description="Quality Assurance Zilla MCP - PostgreSQL Primary Storage"
)

store = QAZillaStore()

# MCP Request/Response Models
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

# Tool Schemas
TOOL_SCHEMAS = {
    'create_test_plan': {
        'name': 'create_test_plan',
        'description': 'Create a new test plan',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'feature': {'type': 'string'},
                'scope': {'type': 'string'},
                'objectives': {'type': 'string'},
            },
            'required': ['title', 'feature', 'scope', 'objectives']
        }
    },
    'list_test_plans': {
        'name': 'list_test_plans',
        'description': 'List all test plans',
        'inputSchema': {'type': 'object', 'properties': {}}
    },
    'create_bug_report': {
        'name': 'create_bug_report',
        'description': 'Create a new bug report',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'severity': {'type': 'string'},
                'priority': {'type': 'string'},
                'steps_to_reproduce': {'type': 'string'},
                'expected': {'type': 'string'},
                'actual': {'type': 'string'},
                'environment': {'type': 'string'},
            },
            'required': ['title', 'severity', 'priority']
        }
    },
    'list_bug_reports': {
        'name': 'list_bug_reports',
        'description': 'List all bug reports',
        'inputSchema': {'type': 'object', 'properties': {}}
    },
}

# MCP Endpoints
@app.post("/mcp/initialize")
async def mcp_initialize(request: MCPRequest) -> MCPResponse:
    return MCPResponse(
        id=request.id,
        result={
            'protocolVersion': '2024-11-05',
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'qazilla-mcp', 'version': '1.0.0'}
        }
    )

@app.post("/mcp/tools/list")
async def mcp_tools_list(request: MCPRequest) -> MCPResponse:
    return MCPResponse(
        id=request.id,
        result={'tools': list(TOOL_SCHEMAS.values())}
    )

@app.post("/mcp/tools/call")
async def mcp_tools_call(request: MCPRequest) -> MCPResponse:
    tool_name = request.params.get('name')
    arguments = request.params.get('arguments', {})

    try:
        if tool_name == 'create_test_plan':
            plan = store.create_test_plan(**arguments)
            result = asdict(plan)
        elif tool_name == 'list_test_plans':
            plans = store.list_test_plans()
            result = [asdict(p) for p in plans]
        elif tool_name == 'create_bug_report':
            bug = store.create_bug_report(**arguments)
            result = asdict(bug)
        elif tool_name == 'list_bug_reports':
            bugs = store.list_bug_reports()
            result = [asdict(b) for b in bugs]
        else:
            return MCPResponse(id=request.id, error={'code': -32601, 'message': f'Unknown tool: {tool_name}'})

        return MCPResponse(id=request.id, result={'content': [{'type': 'text', 'text': json.dumps(result)}]})
    except Exception as e:
        logger.error(f'Tool error: {e}')
        return MCPResponse(id=request.id, error={'code': -32603, 'message': str(e)})

# Health/Info Endpoints
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "qazilla-mcp"}

@app.get("/info")
async def info():
    return {"name": "qazilla-mcp", "version": "1.0.0", "tools": len(TOOL_SCHEMAS)}

@app.get("/")
async def root():
    return {"service": "qazilla-mcp", "version": "1.0.0", "status": "running"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7201))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
