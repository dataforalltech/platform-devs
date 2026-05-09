import yaml
from pathlib import Path

from ..config.settings import AuditSettings
from ..db.store import AuditStore


def get_compliance_checklist(
    store: AuditStore,
    settings: AuditSettings,
    *,
    service: str,
    repo: str,
    env: str,
) -> dict:
    """Retorna checklist dinâmico para um serviço/repo/env."""
    try:
        policy_file = Path(settings.policies_path) / f"{env}.yaml"

        if not policy_file.exists():
            return {
                "error": "NotFound",
                "details": f"Policy not found for env {env}",
                "tool": "get_compliance_checklist",
            }

        with open(policy_file) as f:
            policy = yaml.safe_load(f)

        checklist = []
        min_score = policy.get("min_score", 0.5)

        for category, items in policy.get("required_checkers", {}).items():
            for item_name in items:
                checklist.append(
                    {
                        "category": category,
                        "name": item_name,
                        "required": True,
                        "passed": None,
                    }
                )

        for category, items in policy.get("ideal_checkers", {}).items():
            for item_name in items:
                checklist.append(
                    {
                        "category": category,
                        "name": item_name,
                        "required": False,
                        "passed": None,
                    }
                )

        return {
            "service": service,
            "repo": repo,
            "env": env,
            "min_score": min_score,
            "checklist_items": len(checklist),
            "checklist": checklist,
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "get_compliance_checklist"}
