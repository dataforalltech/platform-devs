from datetime import datetime, timedelta

from ..config.settings import AuditSettings
from ..db.store import AuditStore


def get_audit_report(
    store: AuditStore,
    settings: AuditSettings,
    *,
    service: str | None = None,
    env: str | None = None,
    period_days: int = 30,
) -> dict:
    """Retorna relatório consolidado de conformidade."""
    try:
        audits = store.list_audits(
            service=service,
            env=env,
            limit=100,
        )

        cutoff_date = (datetime.utcnow() - timedelta(days=period_days)).isoformat()
        filtered_audits = [a for a in audits if a["created_at"] >= cutoff_date]

        if not filtered_audits:
            return {
                "period_days": period_days,
                "total_audits": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "pending_count": 0,
                "average_score": 0.0,
            }

        approved = sum(1 for a in filtered_audits if a["status"] == "approved")
        rejected = sum(1 for a in filtered_audits if a["status"] == "rejected")
        pending = sum(1 for a in filtered_audits if a["status"] == "pending_approval")
        auto_approved = sum(1 for a in filtered_audits if a["status"] == "auto_approved")

        avg_score = (
            sum(a["score"] for a in filtered_audits) / len(filtered_audits)
            if filtered_audits
            else 0.0
        )

        by_env = {}
        by_criticality = {}

        for audit in filtered_audits:
            env_key = audit["env"]
            crit_key = audit["criticality"]

            if env_key not in by_env:
                by_env[env_key] = {"count": 0, "passed": 0, "avg_score": 0.0}
            if crit_key not in by_criticality:
                by_criticality[crit_key] = {"count": 0, "passed": 0, "avg_score": 0.0}

            by_env[env_key]["count"] += 1
            by_criticality[crit_key]["count"] += 1
            if audit["passed"]:
                by_env[env_key]["passed"] += 1
                by_criticality[crit_key]["passed"] += 1

        return {
            "period_days": period_days,
            "total_audits": len(filtered_audits),
            "approved_count": approved,
            "auto_approved_count": auto_approved,
            "rejected_count": rejected,
            "pending_count": pending,
            "average_score": round(avg_score, 2),
            "pass_rate_pct": round((approved + auto_approved) / len(filtered_audits) * 100, 1)
            if filtered_audits
            else 0.0,
            "by_env": by_env,
            "by_criticality": by_criticality,
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "get_audit_report"}


def list_audits(
    store: AuditStore,
    settings: AuditSettings,
    *,
    status: str | None = None,
    env: str | None = None,
    service: str | None = None,
    limit: int = 50,
) -> dict:
    """Lista auditorias com filtros."""
    try:
        audits = store.list_audits(status=status, env=env, service=service, limit=limit)

        return {
            "total": len(audits),
            "limit": limit,
            "audits": [
                {
                    "audit_id": a["id"],
                    "service": a["service"],
                    "repo": a["repo"],
                    "env": a["env"],
                    "criticality": a["criticality"],
                    "score": a["score"],
                    "status": a["status"],
                    "created_at": a["created_at"],
                }
                for a in audits
            ],
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "list_audits"}
