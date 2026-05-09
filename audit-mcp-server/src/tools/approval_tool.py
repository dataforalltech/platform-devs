from ..config.settings import AuditSettings
from ..db.store import AuditStore


def submit_audit_approval(
    store: AuditStore,
    settings: AuditSettings,
    *,
    audit_id: str,
    approved_by: str,
    decision: str,
    role: str | None = None,
    notes: str | None = None,
) -> dict:
    """Submete aprovação manual de uma auditoria."""
    try:
        audit = store.get_audit(audit_id)

        if not audit:
            return {
                "error": "NotFound",
                "details": f"Audit {audit_id} not found",
                "tool": "submit_audit_approval",
            }

        valid_decisions = ["approved", "rejected"]
        if decision not in valid_decisions:
            return {
                "error": "ValidationError",
                "details": f"Invalid decision: {decision}. Must be one of {valid_decisions}",
                "tool": "submit_audit_approval",
            }

        store.add_approval(audit_id, approved_by, decision, role, notes)

        if decision == "approved":
            store.update_audit_status(audit_id, "approved", audit["score"], audit["passed"])
        elif decision == "rejected":
            store.update_audit_status(audit_id, "rejected", audit["score"], False)

        approvals = store.get_approvals(audit_id)

        return {
            "audit_id": audit_id,
            "service": audit["service"],
            "decision": decision,
            "approved_by": approved_by,
            "role": role,
            "approvals_count": len(approvals),
            "status": "approved" if decision == "approved" else "rejected",
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "submit_audit_approval"}
