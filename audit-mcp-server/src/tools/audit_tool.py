from pathlib import Path
from typing import Any, Protocol

from ..checkers.docs_checker import DocsChecker
from ..checkers.lint_checker import LintChecker
from ..checkers.resolver import RepoResolver
from ..checkers.security_checker import SecurityChecker
from ..checkers.structure_checker import StructureChecker
from ..checkers.test_checker import TestChecker
from ..config.settings import AuditSettings
from ..db.store import AuditStore


class _Checker(Protocol):
    """Interface estrutural comum dos checkers (todos expõem run estático)."""

    @staticmethod
    def run(repo_path: str, env: str = "dev") -> dict[str, Any]: ...


async def run_audit(
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

        criticality = await store.get_service_criticality(service)
        audit_id = await store.create_audit(
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

        checkers: list[type[_Checker]] = [
            StructureChecker,
            TestChecker,
            SecurityChecker,
            DocsChecker,
            LintChecker,
        ]
        for checker_cls in checkers:
            result = checker_cls.run(resolved_path, env)
            for item in result["items"]:
                all_items.append(item)
                await store.add_audit_item(
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

        # Um item OBRIGATÓRIO que não foi executado não tem evidência nenhuma a
        # favor nem contra — e por isso NÃO pode abrir caminho para auto-aprovação.
        # Antes desta checagem, os dois placeholders de vulnerabilidade do
        # SecurityChecker devolviam passed=True e uma promoção podia ser
        # auto-aprovada por varreduras que nunca rodaram.
        unexecuted_required = [
            i["name"] for i in all_items if i.get("required") and not i.get("executed", True)
        ]

        auto_approve_if_score = approval_rule.get("auto_approve_if_score")
        if auto_approve_if_score and score >= auto_approve_if_score and not unexecuted_required:
            status = "auto_approved"
            await store.update_audit_status(audit_id, status, score, True)
        else:
            status = "pending_approval"
            await store.update_audit_status(audit_id, status, score, score >= policy["min_score"])

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
            # Torna visível para quem consome o resultado QUAIS obrigatórios não
            # rodaram — sem isso, "pending_approval" não distingue "reprovou" de
            # "não foi possível avaliar".
            "unexecuted_required": unexecuted_required,
            "approvals_required": (
                0 if status == "auto_approved" else approval_rule.get("required_approvals", 1)
            ),
        }
    except Exception as e:
        return {"error": "InternalError", "details": str(e), "tool": "run_audit"}


async def get_audit_status(
    store: AuditStore,
    settings: AuditSettings,
    *,
    service: str,
    env: str,
) -> dict:
    """Retorna status da auditoria mais recente."""
    try:
        audit = await store.get_latest_audit(service, env)

        if not audit:
            return {
                "audit_id": None,
                "service": service,
                "env": env,
                "status": "not_audited",
                "score": None,
            }

        items = await store.get_audit_items(audit["id"])
        approvals = await store.get_approvals(audit["id"])

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

    with open(policy_file, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
