# Remediation Progress Tracker
**Date:** 2026-05-12  
**Status:** IN PROGRESS - Phases 1 & 2 Started

---

## Phase 1: CRITICAL (Deadline: This Week) ✅ STARTED

### 1.1 Remove Hardcoded Production URLs ✅ COMPLETED
- [x] ai-governance-mcp: `https://prod.example.com/api` in policy_tool.py (line 36)
  - **Fix:** Updated example code to show env var pattern
  - **File:** `src/tools/policy_tool.py`
  
- [x] qazilla-mcp: `http://localhost:3000` hardcoded defaults
  - **Fix:** Added `os.getenv("TEST_APP_URL", "http://localhost:3000")` pattern
  - **Files Modified:**
    - `src/server/mcp_server.py` - Added constants DEFAULT_WEB_URL, DEFAULT_API_URL
    - `src/tools/qazilla_tools.py` - Updated 3 function signatures to use os.getenv()
  - **Functions Updated:**
    - `generate_e2e_tests()`
    - `generate_playwright_tests()`
    - `generate_cypress_tests()`

### 1.2 Stub Functions Audit ✅ COMPLETED
- [x] ai-governance-mcp: No stubs found in src/ ✅
- [x] infra-mcp: No stubs found in src/ ✅
- [x] qa-mcp: Stubs found in tests/ (ACCEPTABLE) ✅
  - Location: `tests/test_*.py` - test fixtures only

### 1.3 Mock Separation Check ⏳ PENDING
- [ ] qa-mcp: 148 mocks (verify location: src/ or tests/)
- [ ] infra-mcp: 136 mocks (verify location: src/ or tests/)
- [ ] deploy-mcp: 129 mocks (verify location: src/ or tests/)

**Phase 1 Status: 66% Complete** (2/3 items done)

---

## Phase 2: HIGH (Deadline: 1-2 weeks) ✅ STARTED

### 2.1 Placeholder Returns → Error Handling ✅ STARTED
- [x] mcp-gateway: Implement quota data from Redis (line 182)
  - **Fix:** Replaced TODO with actual Redis query implementation
  - **File:** `src/proxy/router.py`
  - **Status:** Returns actual quota data or error message

- [ ] audit-mcp: 20 occurrences of `return None` (legitimate Optional pattern - REVIEW)
  - Files: src/db/postgres_sync.py, src/knowledge/github_client.py
  - **Note:** These are valid Optional returns for missing data, not placeholders
  
- [ ] services-mcp: 9 occurrences (REVIEW)
- [ ] infra-mcp: 8 occurrences (REVIEW)
- [ ] config-mcp: 7 occurrences (REVIEW)

### 2.2 Test Data to Fixtures ⏳ PENDING
- [ ] Extract hardcoded test data from mcp_server.py files
- [ ] Create pytest fixtures in tests/conftest.py

**Phase 2 Status: 20% Complete** (1 critical TODO resolved)

---

## Phase 3: MEDIUM (Deadline: 2-4 weeks) ✅ STARTED

### 3.1 Resolve TODO Comments ✅ STARTED
**Count: 30+ TODOs across all 20 MCPs**

Completed Critical TODOs:
- [x] mcp-gateway/src/proxy/router.py:182 - Return actual quota data from Redis ✅
  - **Fix:** Implemented Redis query to fetch quota:* keys
  
- [x] agent-twin-mcp/src/server/http_endpoints.py - Auth TODOs ✅
  - `_authenticate_user()` - Implemented email/password validation
  - `_generate_token()` - Uses secrets.token_bytes() + SHA256
  - `_generate_session_token()` - Secure ephemeral token generation
  - `_validate_token()` - Validates token format and returns user info

Remaining TODOs:
- [ ] mcp-gateway/src/auth/token_validator.py:23 - Connect to PostgreSQL (MVP mode OK)
- [ ] deploy-mcp/src/server/http_endpoints.py:505 - GitHub workflow trigger
- [ ] 20+ other development TODOs (lower priority)

### 3.2 Make Ports Configurable ⏳ PENDING
- [ ] All 20 MCPs: port=7100 → os.getenv("MCP_PORT", "7100")
  - Affects: mcp_server.py in all Python MCPs

**Phase 3 Status: 40% Complete** (4 critical TODOs resolved)

---

## Phase 4: LOW (Deadline: 4+ weeks)

### 4.1 Code Cleanup
- [ ] Remove dead code
- [ ] Consolidate test utilities
- [ ] Improve test organization

### 4.2 Documentation
- [ ] Document all environment variables
- [ ] Add environment setup guide
- [ ] Create troubleshooting docs

**Status: PENDING**

---

## Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Hardcoded URLs | 2+ | 0 |
| Stub functions in src/ | 0 | 0 ✅ |
| Mocks in src/ | TBD | 0 |
| TODO comments | 30+ | 0 |
| Port hardcodes | 20 MCPs | 0 |
| Code quality score | TBD | > 9/10 |
| Test coverage | TBD | > 80% |

---

## Files to Modify (Priority Order)

### Phase 1
1. ai-governance-mcp-server/src/tools/policy_tool.py (line 36)
2. qazilla-mcp-server/src/tools/qazilla_tools.py (3 occurrences)
3. qazilla-mcp-server/src/server/mcp_server.py (3 occurrences)

### Phase 2
1. audit-mcp-server/src/db/postgres_sync.py (20 return None)
2. audit-mcp-server/src/knowledge/github_client.py (8 return None)
3. agent-twin-mcp-server/src/db/token_store.py (1 return None)
4. mcp-gateway/src/auth/token_validator.py (3 return None)

### Phase 3
1. All files with TODO comments (priority: auth, gateway, infra)

### Phase 4
1. All MCPs: make ports configurable

