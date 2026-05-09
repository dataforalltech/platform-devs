from ..config.settings import AuditSettings
from ..db.store import AuditStore


def get_audit_gate_result(
    store: AuditStore,
    settings: AuditSettings,
    *,
    service: str,
    env: str,
) -> dict:
    """Retorna resultado do gate de auditoria para integração com pipeline-mcp."""
    try:
        audit = store.get_latest_audit(service, env)

        if not audit:
            return {
                "gate_type": "audit_compliance",
                "service": service,
                "env": env,
                "passed": False,
                "reason": "no_audit_found",
                "details": f"No audit found for {service} in {env}",
            }

        passed = audit["status"] in ["approved", "auto_approved"]

        return {
            "gate_type": "audit_compliance",
            "service": service,
            "env": env,
            "audit_id": audit["id"],
            "score": audit["score"],
            "passed": passed,
            "status": audit["status"],
            "reason": "audit_approved" if passed else f"audit_{audit['status']}",
            "details": f"Score: {audit['score']:.1%}, Status: {audit['status']}",
        }
    except Exception as e:
        return {
            "error": "InternalError",
            "details": str(e),
            "tool": "get_audit_gate_result",
        }
