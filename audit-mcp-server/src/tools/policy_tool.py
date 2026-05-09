import yaml
from pathlib import Path

from ..config.settings import AuditSettings
from ..db.store import AuditStore


def get_compliance_policy(
    store: AuditStore,
    settings: AuditSettings,
    *,
    env: str,
) -> dict:
    """Retorna política de conformidade para o ambiente."""
    try:
        policy_file = Path(settings.policies_path) / f"{env}.yaml"

        if not policy_file.exists():
            return {
                "error": "NotFound",
                "details": f"Policy not found for env {env}",
                "tool": "get_compliance_policy",
            }

        with open(policy_file) as f:
            policy = yaml.safe_load(f)

        return {
            "env": policy.get("env"),
            "min_score": policy.get("min_score"),
            "required_checkers": policy.get("required_checkers", {}),
            "ideal_checkers": policy.get("ideal_checkers", {}),
            "approval_rules": policy.get("approval_rules", {}),
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "get_compliance_policy"}


def set_service_criticality(
    store: AuditStore,
    settings: AuditSettings,
    *,
    service: str,
    criticality: str,
    updated_by: str,
) -> dict:
    """Define criticidade de um serviço."""
    try:
        valid_criticalities = ["low", "medium", "high", "critical"]
        if criticality not in valid_criticalities:
            return {
                "error": "ValidationError",
                "details": f"Invalid criticality: {criticality}. Must be one of {valid_criticalities}",
                "tool": "set_service_criticality",
            }

        store.set_service_criticality(service, criticality, updated_by)

        return {
            "service": service,
            "criticality": criticality,
            "updated_by": updated_by,
            "success": True,
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "set_service_criticality"}
