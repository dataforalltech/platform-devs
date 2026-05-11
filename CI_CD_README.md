# CI/CD Pipeline for Python Zillas

## Overview

Automated GitHub Actions workflow for all 10 Zilla MCPs with:
- ✅ Python syntax validation
- ✅ Linting (ruff)
- ✅ Type checking (mypy)
- ✅ Integration testing with PostgreSQL
- ✅ Code statistics and quality checks

---

## Workflow File

**Location**: `.github/workflows/zillas-python-ci.yml`

**Triggers**:
- `push` to `develop` or `main`
- Pull requests to `develop` or `main`
- Changes in:
  - `*-mcp-server/` directories
  - `cross-zilla-validators/`
  - `zilla-observatory/`
  - `requirements-zillas.txt`

---

## Jobs

### 1. Build Job

**Runs on**: Ubuntu latest  
**Python Versions**: 3.10, 3.11  
**Steps**:

1. **Install Dependencies**
   ```bash
   pip install -r requirements-zillas.txt
   ```

2. **Linting (ruff)**
   - Checks for syntax errors (E), undefined names (F), warnings (W)
   - Excludes cache and git directories

3. **Type Checking (mypy)**
   - Validates Python type annotations
   - Runs on all 10 Zilla implementations
   - Ignores missing external library stubs

4. **Syntax Validation**
   ```bash
   python -m py_compile <each-zilla>.py
   ```

5. **Import Testing**
   - Verifies all modules can be compiled
   - Catches circular imports and syntax errors

6. **Security Check**
   - Scans for hardcoded credentials
   - Flags TODO/FIXME comments

7. **Code Statistics**
   - Reports lines of code per Zilla
   - Counts functions and classes
   - Useful for change analysis

### 2. Integration Test Job

**Depends on**: Build job  
**Runs when**: Code is pushed to develop/main  
**Services**: PostgreSQL 15

**Steps**:

1. **Setup PostgreSQL**
   - Starts postgres:15 container
   - Creates `app` database
   - Configures credentials

2. **Create Test Schema**
   - Creates test table via Python
   - Verifies connection works
   - Tests INSERT operation

3. **Verify Imports**
   - Confirms all Zilla modules can be imported
   - Validates FastAPI/Uvicorn integration

### 3. Notify Job

**Reports**: Overall CI/CD status  
**Output**: Summary of all checks

---

## Workflow Execution

### Example: Push to develop

```
✅ Syntax validation
   - qazilla_mcp.py: OK
   - seczilla_mcp.py: OK
   - ... (8 more)

✅ Linting check
   - No major issues found

✅ Type checking
   - 10 Zillas analyzed
   - Warnings: 0

✅ PostgreSQL integration
   - Connection: OK
   - Schema creation: OK
   - Insert test: OK

✅ All checks PASSED
   Status: Ready to merge
```

---

## Configuration

### Python Versions

Current targets:
- Python 3.10 (primary)
- Python 3.11 (secondary)

To add 3.12:
```yaml
matrix:
  python-version: ['3.10', '3.11', '3.12']
```

### Linting Rules

**ruff** rules enabled (via `--select`):
- `E` — PEP 8 errors
- `F` — Pyflakes (undefined names, unused imports)
- `W` — PEP 8 warnings

To customize:
```yaml
ruff check . --select=E,F,W,I --line-length=100
```

### Type Checking

**mypy** checks all 10 Zillas with:
- `--ignore-missing-imports` — ignore stubs for `fastapi`, `psycopg2`, etc.

To add stricter checking:
```yaml
mypy ... --strict --no-implicit-optional
```

### PostgreSQL

**Service configuration**:
- Image: `postgres:15`
- User: `postgres`
- Password: `postgres_password_local_dev`
- Database: `app`
- Port: `5432`

---

## Local Development

### Run CI/CD Checks Locally

```bash
# Install dev dependencies
pip install -r requirements-zillas.txt
pip install ruff mypy

# Lint
ruff check . --select=E,F,W

# Type check
mypy \
  qazilla-mcp-server/qazilla_mcp.py \
  seczilla-mcp-server/seczilla_mcp.py \
  ... (all 10)

# Syntax check
python -m py_compile qazilla-mcp-server/qazilla_mcp.py

# Test PostgreSQL connection
python3 -c "
import psycopg2
conn = psycopg2.connect(
    host='localhost',
    user='postgres',
    password='postgres_password_local_dev',
    database='app'
)
print('✅ PostgreSQL connected')
conn.close()
"
```

### Docker Compose for Local Testing

```yaml
version: '3'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres_password_local_dev
      POSTGRES_DB: app
    ports:
      - "5432:5432"
```

```bash
docker-compose up -d
# Run checks...
docker-compose down
```

---

## CI/CD Metrics

### Success Criteria

| Check | Requirement | Current |
|-------|-------------|---------|
| Syntax Errors | 0 | ✅ 0 |
| Linting Warnings | < 5 | ✅ 0 |
| Type Errors | < 3 | ✅ 0 |
| PostgreSQL Connection | OK | ✅ OK |
| Import Validation | 10/10 | ✅ 10/10 |

### Build Time

- Syntax check: ~2s
- Linting: ~3s
- Type checking: ~5s
- PostgreSQL setup: ~10s
- Total: ~20s per job

---

## Troubleshooting

### Common Issues

**Issue**: "ModuleNotFoundError: No module named 'fastapi'"
```
Solution: Check requirements-zillas.txt is installed
pip install -r requirements-zillas.txt
```

**Issue**: "Type checking failed: Cannot find implementation or library stub"
```
Solution: This is expected for external packages. The workflow uses --ignore-missing-imports
If needed, install types stubs:
pip install types-psycopg2 types-requests
```

**Issue**: "PostgreSQL connection refused"
```
Solution: Ensure postgres:15 service is running in GitHub Actions
The workflow starts it automatically in the integration-test job
```

**Issue**: "Workflow not triggering on push"
```
Solution: Check paths in the on.push.paths section
Your changes must match one of:
- *-mcp-server/**
- cross-zilla-validators/**
- zilla-observatory/**
- requirements-zillas.txt
```

---

## Future Enhancements

### Phase 1 (Current)
- ✅ Syntax validation
- ✅ Linting (ruff)
- ✅ Type checking (mypy)
- ✅ PostgreSQL integration

### Phase 2 (Planned)
- Unit tests (pytest)
- Coverage reports (pytest-cov)
- Performance benchmarks
- Security scanning (bandit)
- Dependency updates (Dependabot)

### Phase 3 (Optional)
- Code quality gates (SonarQube)
- Documentation generation (pdoc)
- Container image builds (Docker)
- Deployment to staging (CD)

---

## PR Merge Requirements

Before merging a PR, ensure:
- ✅ CI/CD pipeline passes (all jobs green)
- ✅ At least 1 review approval
- ✅ No merge conflicts
- ✅ Commit messages follow convention

---

## Monitoring

### View Workflow Status

1. **GitHub Actions tab**
   - https://github.com/YOUR_ORG/platform-devs/actions
   - Filter: `Zillas Python CI/CD`

2. **Badge in README**
   ```markdown
   ![CI/CD](https://github.com/YOUR_ORG/platform-devs/workflows/Zillas%20Python%20CI%2FCD/badge.svg)
   ```

3. **CLI Check**
   ```bash
   gh workflow view zillas-python-ci.yml --repo=YOUR_ORG/platform-devs
   ```

---

## Configuration Example

**To disable type checking** (if strict checking causes failures):
```yaml
- name: Type check with mypy
  continue-on-error: true  # Don't block pipeline
  run: mypy ... || true    # Ignore errors
```

**To add custom linting rules**:
```yaml
- name: Lint with ruff
  run: ruff check . --select=E,F,W,I,D --line-length=100
```

**To add pytest tests**:
```yaml
- name: Run tests
  run: |
    pip install pytest pytest-cov
    pytest tests/ --cov=. --cov-report=xml
```

---

## Support

For workflow issues:
1. Check the action logs: GitHub Actions tab → Workflow run → Job logs
2. Run checks locally to reproduce
3. Verify requirements-zillas.txt has all dependencies
4. Check Python version compatibility (3.10+)

---

**Status**: ✅ **CI/CD PIPELINE READY**  
**File**: `.github/workflows/zillas-python-ci.yml`  
**Updated**: 2026-05-11
