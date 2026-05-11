# ADR-002 — Repository Automation Governance

**Status:** Accepted  
**Date:** 2026-05-11  
**Authors:** caiog  

---

## Context

The platform has 62 active repositories with heterogeneous characteristics: Python microservices, frontends, shared libraries, legacy Java services, deprecated repos, and infrastructure templates. Not all repos are eligible for automated CI/CD pipelines and ACR image builds.

Running automation indiscriminately across all repos risks:
- Triggering builds on deprecated or legacy repos without proper pipelines
- Pushing unintended Docker images to ACR from template or library repos
- Consuming ACR credentials/quota on non-service repos
- Breaking legacy Java/JS services that require non-standard pipelines

## Decision

**All automated operations must filter repositories by:**

```sql
WHERE active = true AND allows_automation = true
```

This filter is the canonical access gate for any operation that:
- Clones or syncs repositories
- Triggers GitHub Actions workflows (CI or CD)
- Builds or pushes Docker images to ACR (`d4all.azurecr.io`)
- Scaffolds pipeline templates into repos
- Collects metrics about CI/ACR health

### Classification columns added to `repositories` table

| Column | Type | Description |
|---|---|---|
| `repo_type` | varchar | `backend`, `frontend`, `lib`, `infra`, `data`, `deprecated` |
| `repo_scope` | varchar | `microservice`, `product`, `tool`, `template`, `deprecated` |
| `allows_automation` | boolean | Gate for automated operations. Managed by platform team. |
| `automation_notes` | text | Required when `false` — explains why automation is excluded. |

### Current scope (as of 2026-05-11)

| Eligible (allows_automation=true) | Count |
|---|---|
| backend microservices | 27 |
| backend products | 2 |
| frontend products | 7 |
| infra tools/products | 2 |
| **Total** | **38** |

| Excluded (allows_automation=false) | Reason |
|---|---|
| 14 libs (`platform-*-lib`) | No Dockerfile — CI only, no ACR image |
| 3 deprecated repos | End-of-life, no new builds |
| `common-platform` | Legacy monolith, non-standard pipeline |
| `database-manager` | Java tooling, no Docker pipeline |
| `processor-platform` | Java service, requires separate pipeline |
| `data-plataform-v20` | Legacy JS stack, non-standard |
| `platform-19` | Legacy frontend version |
| `platform-operation` | Operational repo, not a deployable service |
| `platform-service-template` | Template — must not generate its own image |

## Implementation

The canonical filter is centralized in `db/repo_filters.py`:

```python
from repo_filters import get_automation_repos, AUTOMATION_FILTER_SQL

# In Python:
repos = get_automation_repos(conn)  # returns list of eligible repos

# In raw SQL:
cur.execute(f"SELECT id, name FROM repositories {AUTOMATION_FILTER_SQL}")

# To validate a specific repo before operating:
assert_repo_allowed(conn, repo_name)  # raises PermissionError if excluded
```

All scripts in `db/` and tools in `deploy-mcp-server/` must import from `repo_filters` instead of writing the filter inline.

## Consequences

- **Positive:** Prevents accidental automation on 24 repos explicitly excluded by the platform team.
- **Positive:** Single source of truth — changing scope means updating the DB column, not editing scripts.
- **Positive:** `automation_notes` provides audit trail for why each repo is excluded.
- **Negative:** New repos added to GitHub must be manually classified before automation runs. This is intentional — opt-in is safer than opt-out.

## Change process

To add or remove a repo from automation scope:
1. Update `allows_automation` and `automation_notes` in the `repositories` table
2. Record the reason in this ADR's table above
3. The change takes effect on the next automation run — no code changes required

---

*Supersedes: no prior ADR. Related: ADR-001 (Python/PostgreSQL migration).*
