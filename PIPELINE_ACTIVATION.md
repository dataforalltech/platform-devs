# Pipeline Activation Workflow — 8 Zillas

**Status**: PR #7 merged to `develop`  
**Next**: Execute pipeline-mcp registrations  
**Timeline**: ~60 minutes (including human approvals)

---

## Step 1: Auto-Merge PR #7 (DEV Environment)

PR #7 will automatically merge to `develop` once gates pass:
- ✅ qa_tests: Profile prompts build successfully
- ✅ pr_approved: At least 1 approval from code review

**Expected**: Merge happens automatically after approvals.

---

## Step 2: Register 8 Zillas in Pipeline-MCP

Once merged to develop, register each service:

```bash
# Register all 8 Zillas
for service in archzilla backzilla frontzilla-pixelfera opszilla pozilla productzilla qazilla seczilla; do
  pipeline-mcp.register_pipeline(
    service="${service}",
    repo="dataforalltech/platform-devs/${service}-mcp-server",
    base_branch="develop"
  )
done
```

**Result**: 8 services registered with current_env="dev"

---

## Step 3: Configure Quality Gates

For each Zilla, set gate requirements:

```bash
for service in archzilla backzilla frontzilla-pixelfera opszilla pozilla productzilla qazilla seczilla; do
  pipeline-mcp.set_pipeline_config(
    service="${service}",
    gates_required={
      "homol": ["qa_tests", "pr_approved"],
      "prod": ["qa_tests", "security_scan", "pr_approved", "health_check"]
    }
  )
done
```

**Result**: 16 quality gates configured (2 per service for HML + 4 for PROD)

---

## Step 4: Test First Promotion (ArchZilla)

Promote ArchZilla from dev → hml:

```bash
promotion = pipeline-mcp.promote_service(
  service="archzilla",
  from_env="dev",
  to_env="homol",
  promoted_by="releasemgr@dataforalltech.tech",
  reason="FASE 4 complete. Profile-based prompts validated. Ready for homolog testing."
)
# Returns: promotion_id, pr_url, gates_status
```

**Human Action**: Release Manager reviews PR in GitHub, approves gates.

```bash
pipeline-mcp.approve_promotion(
  promotion_id=promotion['promotion_id'],
  approved_by="releasemgr@dataforalltech.tech"
)
```

**Result**: ArchZilla deployed to HML environment

---

## Step 5: Promote Remaining 7 Zillas (Parallel)

Once ArchZilla validates in HML:

```bash
# Parallel promotions (dev → hml)
for service in backzilla frontzilla-pixelfera opszilla pozilla productzilla qazilla seczilla; do
  pipeline-mcp.promote_service(
    service="${service}",
    from_env="dev",
    to_env="homol",
    promoted_by="releasemgr@dataforalltech.tech",
    reason="Following ArchZilla HML validation. All gates passing."
  )
done
```

**Duration**: 1-2 hours (serial human approvals)

---

## Step 6: Monitor Pipeline Health

Check overall status:

```bash
zilla-observatory.get_pipeline_health()
# Expected:
# {
#   "total_services": 8,
#   "deployed_prod": 0,
#   "in_homol": 8,
#   "gate_pass_rate": 95%+,
#   "cycle_time_avg": "~2.5 hours",
#   "blocked_services": 0
# }
```

---

## Step 7: Promote to PROD (After HML Validation)

After 1-5 days HML testing:

```bash
# Promote ArchZilla hml → prod
promotion = pipeline-mcp.promote_service(
  service="archzilla",
  from_env="homol",
  to_env="prod",
  promoted_by="releasemgr@dataforalltech.tech",
  reason="ArchZilla v1.3.0 validated in HML. All security scans passed. Ready for production."
)
```

**Gates Required (PROD)**:
- ✅ qa_tests
- ✅ security_scan
- ✅ pr_approved  
- ✅ health_check (post-deployment)

**Human Action**: Auditor approves in GitHub.

```bash
pipeline-mcp.approve_promotion(
  promotion_id=promotion['promotion_id'],
  approved_by="auditor@dataforalltech.tech"
)
```

---

## Expected Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Register 8 services | 5 min | Parallel registration |
| Configure gates | 5 min | Parallel config |
| ArchZilla test (dev→hml) | 15 min | Serial, human approval |
| Validate in HML | 1-5 days | Testing & validation |
| Promote 7 Zillas to HML | 2 hours | Serial human approvals |
| Promote to PROD | 20 min | Serial, canary + full rollout |
| **Total to Production** | **~3-6 days** | Including HML validation |

---

## Success Criteria

- [x] FASE 4 implementation: Profile prompts ✅
- [x] Pipeline-MCP integration: Quality gates ✅
- [ ] 8 Zillas registered
- [ ] DEV gates passing (100%)
- [ ] ArchZilla in HML
- [ ] All 8 Zillas in HML
- [ ] All 8 Zillas in PROD
- [ ] Observable metrics confirmed
- [ ] Team training completed

---

## Next Steps

1. **NOW**: Get PR #7 approved and merged (1 code review)
2. **Then**: Execute Step 2-3 (registrations + gates)
3. **Then**: Test Step 4 (ArchZilla first promotion)
4. **Then**: Scale to all 8 (Step 5)
5. **Then**: Production readiness review (Step 6-7)

