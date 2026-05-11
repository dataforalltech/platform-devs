# 🧪 Test Plan — Python Zilla MCPs (v2.1.0)

**Date**: 2026-05-11 | **Duration**: 2 weeks | **Status**: Ready to Execute

---

## 📋 Test Scope

### In Scope
- ✅ All 10 Python Zilla MCPs (qazilla, seczilla, archzilla, backzilla, frontzilla, opszilla, pozilla, productzilla, cross-zilla-validators, zilla-observatory)
- ✅ PostgreSQL integration (schema, data persistence, migrations)
- ✅ FastAPI HTTP endpoints
- ✅ Docker containerization
- ✅ Kubernetes deployment
- ✅ Performance under load

### Out of Scope
- ❌ Legacy TypeScript/SQLite code (removed)
- ❌ npm/Node.js builds
- ❌ SQLite data migration from prod (if any)

---

## 🎯 Test Strategy

| Level | Type | Tools | Coverage |
|-------|------|-------|----------|
| **Unit** | Function tests | pytest | 80%+ |
| **Integration** | DB + API tests | pytest + PostgreSQL | 70%+ |
| **E2E** | Full workflow | Playwright/k6 | 50%+ |
| **Performance** | Load + stress | k6 | 10, 100, 1000 VUs |
| **Security** | SAST + DAST | bandit + OWASP ZAP | 100% of endpoints |

---

## 1. Unit Tests

### Framework: pytest

### Test Files
```
tests/
├── test_qazilla.py           # TestPlan CRUD operations
├── test_seczilla.py          # Security validation flows
├── test_archzilla.py         # Architecture DSL tests
├── test_backzilla.py         # Backend schema tests
├── test_frontzilla.py        # UI component tests
├── test_opszilla.py          # Infrastructure tests
├── test_pozilla.py           # Product workflows
├── test_productzilla.py      # Product management
├── test_cross_validators.py  # Cross-Zilla validator logic
├── test_observatory.py       # Observability/monitoring
└── conftest.py              # Shared fixtures
```

### Sample Test Cases

#### qazilla_mcp.py
```python
# tests/test_qazilla.py
import pytest
from qazilla_mcp import create_test_plan, get_test_plan, list_test_plans

@pytest.fixture
def db():
    # Setup test database
    yield postgres_test_db
    # Teardown

def test_create_test_plan_valid(db):
    """Test creating a valid test plan"""
    result = create_test_plan(
        title="Login Flow",
        feature="Authentication",
        scope="Login endpoint",
        objectives="Validate login success/failure"
    )
    assert result.id.startswith("tp_")
    assert result.status == "draft"
    assert result.title == "Login Flow"

def test_create_test_plan_missing_title(db):
    """Test creating test plan without title → error"""
    with pytest.raises(ValueError):
        create_test_plan(
            title=None,
            feature="Feature",
            scope="Scope",
            objectives="Obj"
        )

def test_list_test_plans_pagination(db):
    """Test pagination works (limit + offset)"""
    for i in range(25):
        create_test_plan(
            title=f"Plan {i}",
            feature="Feature",
            scope="Scope",
            objectives="Obj"
        )
    
    page1 = list_test_plans(limit=10, offset=0)
    page2 = list_test_plans(limit=10, offset=10)
    
    assert len(page1) == 10
    assert len(page2) == 10
    assert page1[0].id != page2[0].id
```

### Coverage Target
- **Target**: 80%+
- **Tool**: `pytest --cov=qazilla_mcp --cov-report=html`
- **Success**: All branches covered, no orphaned code

---

## 2. Integration Tests

### PostgreSQL Setup
```python
# tests/conftest.py
import psycopg2
import pytest

@pytest.fixture(scope="session")
def postgres_connection():
    """Connect to test PostgreSQL database"""
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password="test_password",
        database="test_app"
    )
    yield conn
    conn.close()

@pytest.fixture(autouse=True)
def setup_database(postgres_connection):
    """Create schema and seed data before each test"""
    cursor = postgres_connection.cursor()
    
    # Load DDL
    with open("db/create_zilla_tables.sql") as f:
        cursor.execute(f.read())
    
    postgres_connection.commit()
    yield
    
    # Cleanup
    cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    postgres_connection.commit()
```

### Test Cases (API + DB)
```python
# tests/test_integration.py
def test_create_test_plan_persists_in_db(setup_database):
    """Create via API, verify in PostgreSQL"""
    plan = create_test_plan(
        title="API Test",
        feature="Users",
        scope="/api/users",
        objectives="Validate CRUD"
    )
    
    # Query PostgreSQL directly
    cursor = setup_database.cursor()
    cursor.execute(
        "SELECT title FROM test_plans WHERE id = %s",
        (plan.id,)
    )
    row = cursor.fetchone()
    
    assert row[0] == "API Test"

def test_concurrent_inserts_no_corruption(setup_database):
    """Multiple threads inserting simultaneously"""
    import concurrent.futures
    
    def insert_plan(i):
        return create_test_plan(
            title=f"Plan {i}",
            feature="Feature",
            scope="Scope",
            objectives="Obj"
        )
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(insert_plan, range(100)))
    
    assert len(results) == 100
    
    cursor = setup_database.cursor()
    cursor.execute("SELECT COUNT(*) FROM test_plans")
    count = cursor.fetchone()[0]
    
    assert count == 100  # No lost inserts
```

---

## 3. API / E2E Tests

### Tool: Playwright (Web) + httpx (HTTP)

```python
# tests/test_e2e_qazilla.py
import httpx
import pytest

BASE_URL = "http://localhost:7201"

@pytest.fixture
def client():
    return httpx.Client(base_url=BASE_URL)

def test_create_and_retrieve_test_plan(client):
    """Create a test plan via API, then retrieve it"""
    # Create
    response = client.post(
        "/mcp/tools/call",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_test_plan",
                "arguments": {
                    "title": "E2E Test Plan",
                    "feature": "API",
                    "scope": "qazilla",
                    "objectives": "Validate create + retrieve"
                }
            }
        }
    )
    assert response.status_code == 200
    plan_id = response.json()["result"]["id"]
    
    # Retrieve
    response = client.post(
        "/mcp/tools/call",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_test_plan",
                "arguments": {"plan_id": plan_id}
            }
        }
    )
    assert response.status_code == 200
    assert response.json()["result"]["title"] == "E2E Test Plan"

def test_health_endpoint():
    """Simple health check"""
    response = httpx.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

---

## 4. Performance Tests

### Tool: k6

```javascript
// tests/load-test-qazilla.js
import http from 'k6/http';
import { check, group } from 'k6';

export let options = {
  stages: [
    { duration: '2m', target: 10 },      // Ramp-up to 10 users
    { duration: '5m', target: 100 },     // Ramp-up to 100 users
    { duration: '2m', target: 0 },       // Ramp-down to 0 users
  ],
  thresholds: {
    'http_req_duration': ['p(95)<500', 'p(99)<1000'], // <500ms p95, <1s p99
    'http_req_failed': ['rate<0.1'],  // <10% error rate
  },
};

export default function () {
  group('Create Test Plan', () => {
    let res = http.post('http://localhost:7201/mcp/tools/call', {
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: {
        name: 'create_test_plan',
        arguments: {
          title: `Load Test Plan ${__VU}`,
          feature: 'Feature',
          scope: 'Scope',
          objectives: 'Objectives'
        }
      }
    });

    check(res, {
      'create succeeded': (r) => r.status === 200,
      'response time < 500ms': (r) => r.timings.duration < 500,
    });
  });

  group('List Test Plans', () => {
    let res = http.post('http://localhost:7201/mcp/tools/call', {
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: {
        name: 'list_test_plans',
        arguments: { limit: 10 }
      }
    });

    check(res, {
      'list succeeded': (r) => r.status === 200,
    });
  });
}
```

### Run Test
```bash
# Light test (10 concurrent users)
k6 run --vus 10 --duration 5m tests/load-test-qazilla.js

# Expected output:
# ✅ create succeeded 100%
# ✅ response time < 500ms p95
# ✅ http_req_failed rate < 0.1
```

---

## 5. Security Tests

### SAST (Static Analysis)
```bash
# Bandit - Find security issues in Python
pip install bandit
bandit -r . -f json -o bandit-report.json

# Expected: 0 high-severity issues
```

### DAST (Dynamic Analysis)
```bash
# OWASP ZAP - Web application security scanner
docker run -t owasp/zap2docker-stable \
  zap-baseline.py \
  -t http://localhost:7201 \
  -r zap-report.html

# Expected: 0 high-severity vulnerabilities
```

### Dependency Scan
```bash
# Safety - Check for known vulnerabilities in dependencies
pip install safety
safety check --json > safety-report.json

# Expected: 0 vulnerabilities
```

---

## 6. Smoke Test Suite (Pre-Deployment)

Quick validation before deployment (15 minutes):

```bash
#!/bin/bash
# tests/smoke-test.sh

echo "🔥 Smoke Test — Pre-Deployment Validation"

# 1. Health checks
echo "📌 Health checks..."
for port in 7201 7202 7203 7204 7205 7206 7207 7208 7209 7210; do
  response=$(curl -s http://localhost:$port/health)
  if [[ $response == *"ok"* ]]; then
    echo "✅ Zilla on port $port: OK"
  else
    echo "❌ Zilla on port $port: FAILED"
    exit 1
  fi
done

# 2. Create test plan (qazilla)
echo "📌 Create test plan..."
response=$(curl -s -X POST http://localhost:7201/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"create_test_plan","arguments":{"title":"Smoke Test","feature":"Feature","scope":"Scope","objectives":"Test"}}}')

if [[ $response == *"tp_"* ]]; then
  echo "✅ Test plan created"
else
  echo "❌ Failed to create test plan"
  exit 1
fi

# 3. Database connectivity
echo "📌 Database connectivity..."
psql -h localhost -U postgres -d app -c "SELECT COUNT(*) FROM test_plans" && echo "✅ PostgreSQL connected" || exit 1

echo "✅ All smoke tests passed!"
```

---

## 7. UAT Checklist (User Acceptance Testing)

Product Owner sign-off:

- [ ] All 10 Zillas running and healthy
- [ ] Test plans can be created and retrieved
- [ ] Security rules are properly validated
- [ ] Architecture decisions persist
- [ ] Performance meets SLAs (p95 < 500ms)
- [ ] No data loss after restart
- [ ] Logs are informative and searchable
- [ ] Alerts trigger on critical errors

---

## 8. Test Execution Timeline

| Phase | Week | Tests | Duration | Owners |
|-------|------|-------|----------|--------|
| **Unit** | W1 | pytest (all) | 30min | Engineering |
| **Integration** | W1 | pytest + PG | 1h | Engineering |
| **E2E** | W1 | Playwright | 45min | QA |
| **Performance** | W2 | k6 + monitoring | 2h | DevOps |
| **Security** | W2 | bandit + ZAP | 1.5h | Security |
| **Smoke** | Pre-deploy | 15min | Engineering |
| **UAT** | Pre-release | 1h | Product |

---

## 9. Success Criteria

### Unit Tests
- ✅ 80%+ code coverage
- ✅ All tests pass
- ✅ No flaky tests

### Integration Tests
- ✅ PostgreSQL CRUD operations 100%
- ✅ Data consistency verified
- ✅ Connection pooling works

### E2E Tests
- ✅ Full workflows end-to-end
- ✅ Cross-Zilla interactions work
- ✅ Error handling graceful

### Performance
- ✅ p95 latency < 500ms
- ✅ p99 latency < 1s
- ✅ Error rate < 0.1%
- ✅ Support 100 concurrent users

### Security
- ✅ 0 high-severity vulnerabilities
- ✅ All OWASP Top 10 reviewed
- ✅ Dependencies scanned for CVEs

---

## 10. Regression Test Suite

Post-deployment, run weekly:

```bash
# regression-suite.sh
pytest tests/ -k "critical" --tb=short
k6 run tests/load-test-qazilla.js --vus 50
bandit -r . --quiet
```

---

## Sign-Off

| Role | Name | Status |
|------|------|--------|
| QA Lead | QAZilla | Ready to execute |
| Security | SecZilla | Pending SAST/DAST |
| DevOps | OpZilla | Ready for load tests |

**Overall**: ✅ **Test plan is complete and executable**

---

**Next**: Execute tests in order (unit → integration → E2E → performance → security)
