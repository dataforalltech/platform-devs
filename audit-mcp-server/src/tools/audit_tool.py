import json
from pathlib import Path

from ..checkers.docs_checker import DocsChecker
from ..checkers.lint_checker import LintChecker
from ..checkers.resolver import RepoResolver
from ..checkers.security_checker import SecurityChecker
from ..checkers.structure_checker import StructureChecker
from ..checkers.test_checker import TestChecker
from ..config.settings import AuditSettings
from ..db.store import AuditStore


def run_audit(
    store: AuditStore,
    settings: AuditSettings,
    *,
    service: str,
    repo: str,
    env: str,
    repo_path: str | None = None,
) -> dict:
    """Executa auditoria completa do repo."""
    try:
        resolver = RepoResolver(settings.github_token, settings.github_org)
        resolved_path = resolver.resolve(repo, repo_path, env)

        if not resolved_path:
            return {
                "error": "ValidationError",
                "details": f"Cannot resolve repo path for {repo}",
                "tool": "run_audit",
            }

        criticality = store.get_service_criticality(service)
        audit_id = store.create_audit(
            service=service,
            repo=repo,
            env=env,
            criticality=criticality,
            score=0.0,
            passed=False,
            status="pending_approval",
            checklist={},
        )

        all_items = []
        scores = []

        for checker_cls in [
            StructureChecker,
            TestChecker,
            SecurityChecker,
            DocsChecker,
            LintChecker,
        ]:
            result = checker_cls.run(resolved_path, env)
            for item in result["items"]:
                all_items.append(item)
                store.add_audit_item(
                    audit_id,
                    item["category"],
                    item["name"],
                    item["required"],
                    item["passed"],
                    item.get("details"),
                )
            scores.append(result["score"])

        score = sum(scores) / len(scores) if scores else 0.0

        policy = _load_policy(settings.policies_path, env)
        approval_rule = policy.get("approval_rules", {}).get(criticality, {})

        auto_approve_if_score = approval_rule.get("auto_approve_if_score")
        if auto_approve_if_score and score >= auto_approve_if_score:
            status = "auto_approved"
            store.update_audit_status(audit_id, status, score, True)
        else:
            status = "pending_approval"
            store.update_audit_status(audit_id, status, score, score >= policy["min_score"])

        return {
            "audit_id": audit_id,
            "service": service,
            "repo": repo,
            "env": env,
            "criticality": criticality,
            "score": round(score, 2),
            "passed": score >= policy["min_score"],
            "status": status,
            "checklist_count": len(all_items),
            "approvals_required": 0
            if status == "auto_approved"
            else approval_rule.get("required_approvals", 1),
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "run_audit"}


def get_audit_status(
    store: AuditStore,
    settings: AuditSettings,
    *,
    service: str,
    env: str,
) -> dict:
    """Retorna status da auditoria mais recente."""
    try:
        audit = store.get_latest_audit(service, env)

        if not audit:
            return {
                "audit_id": None,
                "service": service,
                "env": env,
                "status": "not_audited",
                "score": None,
            }

        items = store.get_audit_items(audit["id"])
        approvals = store.get_approvals(audit["id"])

        return {
            "audit_id": audit["id"],
            "service": service,
            "env": env,
            "criticality": audit["criticality"],
            "score": audit["score"],
            "passed": audit["passed"],
            "status": audit["status"],
            "created_at": audit["created_at"],
            "updated_at": audit["updated_at"],
            "items_count": len(items),
            "approvals_count": len(approvals),
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "get_audit_status"}


def _load_policy(policies_path: str, env: str) -> dict:
    """Carrega policy YAML para o ambiente."""
    import yaml

    policy_file = Path(policies_path) / f"{env}.yaml"
    if not policy_file.exists():
        return {"min_score": 0.5, "required_checkers": {}, "ideal_checkers": {}}

    with open(policy_file) as f:
        return yaml.safe_load(f) or {}
