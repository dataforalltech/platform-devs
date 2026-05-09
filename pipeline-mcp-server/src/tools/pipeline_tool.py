from __future__ import annotations

import logging
from typing import Any

import httpx

from ..db.store import PipelineStore

_log = logging.getLogger(__name__)

# Branch mapping: source → target per promotion direction
_BRANCH_MAP: dict[str, tuple[str, str]] = {
    "dev->homol": ("develop", "homol"),
    "homol->prod": ("homol", "main"),
}

# PRs targeting these branches are auto-approved/merged by pipeline-mcp
_AUTO_APPROVE_TARGETS = {"develop"}

# These promotions require human approval — pipeline creates PR but does not merge
_HUMAN_APPROVAL_REQUIRED = {"homol", "prod"}


def register_pipeline(
    store: PipelineStore,
    service: str,
    repo: str,
    base_branch: str = "develop",
) -> dict:
    return store.register_pipeline(service=service, repo=repo, base_branch=base_branch)


def get_pipeline(store: PipelineStore, service: str) -> dict:
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}
    return pipeline


def list_pipeline(
    store: PipelineStore,
    env: str | None = None,
    status: str | None = None,
) -> dict:
    pipelines = store.list_pipelines(env=env, status=status)
    return {"total": len(pipelines), "filters": {"env": env, "status": status}, "pipelines": pipelines}


def promote_service(
    store: PipelineStore,
    service: str,
    from_env: str,
    to_env: str,
    promoted_by: str,
    reason: str | None = None,
    github_token: str = "",
    github_org: str = "",
) -> dict:
    """Promove serviço entre ambientes.

    DEV→HML e HML→PROD: cria PR via GitHub e aguarda aprovação humana.
    O merge só ocorre quando humano chama approve_promotion().
    """
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service, "can_promote": False}

    if pipeline.get("blocked"):
        return {
            "error": "service_blocked",
            "service": service,
            "block_reason": pipeline.get("block_reason"),
            "can_promote": False,
        }

    if pipeline.get("current_env") != from_env:
        return {
            "error": "env_mismatch",
            "service": service,
            "current_env": pipeline.get("current_env"),
            "requested_from_env": from_env,
            "can_promote": False,
        }

    # Verify gates
    gates_config: dict[str, list[str]] = pipeline.get("gates_config") or {}
    required_gates = gates_config.get(to_env, [])
    gate_results = store.get_gates(service, from_env)
    gate_map = {g["gate_type"]: g for g in gate_results}
    failed_gates = [gt for gt in required_gates if not gate_map.get(gt, {}).get("passed")]
    gates_snapshot = {g["gate_type"]: bool(g["passed"]) for g in gate_results}

    if failed_gates:
        return {
            "can_promote": False,
            "service": service,
            "from_env": from_env,
            "to_env": to_env,
            "failed_gates": failed_gates,
            "gates_snapshot": gates_snapshot,
        }

    direction = f"{from_env}->{to_env}"
    branch_pair = _BRANCH_MAP.get(direction)
    if branch_pair is None:
        return {"error": "invalid_direction", "direction": direction, "can_promote": False}

    source_branch, target_branch = branch_pair
    repo_name = pipeline.get("repo", "")

    # HML and PROD: create PR, wait for human approval
    pr_number: int | None = None
    pr_url: str | None = None
    promotion_status = "waiting_approval"

    pr_result = _create_pr(
        github_token=github_token,
        github_org=github_org,
        repo=repo_name,
        source_branch=source_branch,
        target_branch=target_branch,
        title=f"[{to_env.upper()}] Promote {service}: {source_branch} → {target_branch}",
        body=(
            f"Pipeline promotion: **{service}** `{from_env}` → `{to_env}`\n\n"
            f"Promoted by: {promoted_by}\n"
            f"Reason: {reason or 'N/A'}\n\n"
            f"**⚠️ Esta PR requer aprovação humana antes do merge.**\n\n"
            f"Gates: {gates_snapshot}"
        ),
    )
    if pr_result.get("success"):
        pr_number = pr_result["pr_number"]
        pr_url = pr_result["pr_url"]
    elif pr_result.get("unavailable"):
        promotion_status = "pending"
        _log.warning("github_unavailable service=%s — promotion registered as pending", service)
    else:
        return {
            "can_promote": True,
            "promoted": False,
            "service": service,
            "from_env": from_env,
            "to_env": to_env,
            "status": "failed",
            "error": pr_result.get("error"),
        }

    promo_id = store.add_promotion(
        service=service,
        from_env=from_env,
        to_env=to_env,
        promoted_by=promoted_by,
        reason=reason,
        gates_snapshot=gates_snapshot,
        deploy_ref=target_branch,
        status=promotion_status,
        pr_number=pr_number,
        pr_url=pr_url,
    )

    return {
        "can_promote": True,
        "promoted": True,
        "service": service,
        "from_env": from_env,
        "to_env": to_env,
        "promoted_by": promoted_by,
        "promotion_id": promo_id,
        "status": promotion_status,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "message": (
            f"PR criada: {pr_url}. "
            f"Aguardando aprovação humana. Após aprovar, chame approve_promotion(promotion_id={promo_id})."
        ),
        "gates_snapshot": gates_snapshot,
    }


def approve_promotion(
    store: PipelineStore,
    promotion_id: int,
    approved_by: str,
    github_token: str = "",
    github_org: str = "",
) -> dict:
    """Registra aprovação humana e executa o merge da PR de HML/PROD."""
    promotion = store.get_promotion(promotion_id)
    if promotion is None:
        return {"error": "not_found", "promotion_id": promotion_id}

    if promotion.get("status") not in ("waiting_approval", "pending"):
        return {
            "error": "invalid_status",
            "promotion_id": promotion_id,
            "current_status": promotion.get("status"),
            "message": "Somente promoções com status waiting_approval ou pending podem ser aprovadas.",
        }

    service = promotion["service"]
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "service_not_found", "service": service}

    # Execute merge via GitHub API
    repo_name = pipeline.get("repo", "")
    pr_number = promotion.get("pr_number")
    merge_result: dict[str, Any] = {"success": True}

    if pr_number and github_token and github_org:
        merge_result = _merge_pr(
            github_token=github_token,
            github_org=github_org,
            repo=repo_name,
            pr_number=pr_number,
            commit_message=f"Merge PR #{pr_number} — {service} {promotion['from_env']}→{promotion['to_env']} (approved by {approved_by})",
        )

    if not merge_result.get("success") and not merge_result.get("unavailable"):
        return {
            "approved": False,
            "promotion_id": promotion_id,
            "error": merge_result.get("error"),
            "message": "Aprovação registrada mas merge falhou. Execute o merge manualmente.",
        }

    store.approve_promotion(promotion_id=promotion_id, approved_by=approved_by)
    store.update_pipeline_env(service=service, env=promotion["to_env"])

    return {
        "approved": True,
        "promotion_id": promotion_id,
        "service": service,
        "from_env": promotion["from_env"],
        "to_env": promotion["to_env"],
        "approved_by": approved_by,
        "pr_number": pr_number,
        "merge_sha": merge_result.get("sha"),
        "message": f"{service} promovido para {promotion['to_env']} com sucesso.",
    }


def watch_prs(
    store: PipelineStore,
    github_token: str = "",
    github_org: str = "",
    repos: list[str] | None = None,
) -> dict:
    """Escaneia PRs abertas nos repos registrados no pipeline.

    PRs targeting 'develop': avalia gates e auto-aprova/mergia se todos passam.
    PRs targeting 'homol'/'main': lista para aprovação humana (não toca).
    """
    if not github_token or not github_org:
        return {
            "error": "github_not_configured",
            "message": "Configure PIPELINE_GITHUB_TOKEN e PIPELINE_GITHUB_ORG para usar watch_prs.",
        }

    # Determine repos to watch
    if repos:
        repo_list = repos
    else:
        pipelines = store.list_pipelines()
        repo_list = list({p["repo"] for p in pipelines if p.get("repo")})

    if not repo_list:
        return {"message": "Nenhum repo registrado no pipeline.", "repos_checked": 0}

    auto_approved: list[dict] = []
    waiting_human: list[dict] = []
    errors: list[dict] = []

    for repo in repo_list:
        prs_result = _list_open_prs(github_token=github_token, github_org=github_org, repo=repo)
        if not prs_result.get("success"):
            errors.append({"repo": repo, "error": prs_result.get("error")})
            continue

        for pr in prs_result.get("prs", []):
            base = pr.get("base_branch", "")
            pr_num = pr.get("number")
            pr_url = pr.get("url")
            pr_title = pr.get("title", "")

            if base in _AUTO_APPROVE_TARGETS:
                # Find service for this repo
                service = _find_service_for_repo(store, repo)
                can_auto = True
                gate_details = "no gates required for dev"

                if service:
                    # Check if qa_tests gate passed for this service/dev
                    gates = store.get_gates(service, "dev")
                    gate_map = {g["gate_type"]: g for g in gates}
                    qa = gate_map.get("qa_tests")
                    if qa and not qa["passed"]:
                        can_auto = False
                        gate_details = "qa_tests gate failed"
                    elif not qa:
                        gate_details = "qa_tests gate not evaluated — proceeding with auto-approve"

                if can_auto:
                    merge_result = _merge_pr(
                        github_token=github_token,
                        github_org=github_org,
                        repo=repo,
                        pr_number=pr_num,
                        commit_message=f"Auto-merge PR #{pr_num}: {pr_title} [pipeline-mcp]",
                    )
                    auto_approved.append({
                        "repo": repo,
                        "pr_number": pr_num,
                        "pr_url": pr_url,
                        "title": pr_title,
                        "target_branch": base,
                        "merged": merge_result.get("success", False),
                        "merge_sha": merge_result.get("sha"),
                        "error": merge_result.get("error") if not merge_result.get("success") else None,
                        "gate_details": gate_details,
                    })
                else:
                    waiting_human.append({
                        "repo": repo,
                        "pr_number": pr_num,
                        "pr_url": pr_url,
                        "title": pr_title,
                        "target_branch": base,
                        "reason": gate_details,
                    })

            elif base in ("homol", "main"):
                waiting_human.append({
                    "repo": repo,
                    "pr_number": pr_num,
                    "pr_url": pr_url,
                    "title": pr_title,
                    "target_branch": base,
                    "reason": "human approval required for homol/prod",
                })

    return {
        "repos_checked": len(repo_list),
        "auto_approved_count": len(auto_approved),
        "waiting_human_count": len(waiting_human),
        "auto_approved": auto_approved,
        "waiting_human": waiting_human,
        "errors": errors,
    }


def block_service(store: PipelineStore, service: str, reason: str, blocked_by: str) -> dict:
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}
    result = store.block_pipeline(service=service, reason=reason, blocked_by=blocked_by)
    return {"blocked": True, "service": service, "pipeline": result}


def rollback(
    store: PipelineStore,
    service: str,
    env: str,
    to_version: str,
    rolled_back_by: str,
    reason: str | None = None,
) -> dict:
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}

    store.update_pipeline_env(service=service, env="rollback", version=to_version)
    promo_id = store.add_promotion(
        service=service,
        from_env=env,
        to_env="rollback",
        promoted_by=rolled_back_by,
        reason=reason or f"Rollback to {to_version}",
        gates_snapshot={},
        deploy_ref=to_version,
        status="success",
    )
    store.complete_promotion(promo_id, "success")
    return {
        "rolled_back": True,
        "service": service,
        "env": env,
        "to_version": to_version,
        "rolled_back_by": rolled_back_by,
        "promotion_id": promo_id,
    }


def get_promotion_history(store: PipelineStore, service: str | None = None, limit: int = 20) -> dict:
    history = store.get_promotion_history(service=service, limit=limit)
    return {"total": len(history), "service": service, "limit": limit, "promotions": history}


def get_pipeline_overview(store: PipelineStore) -> dict:
    return store.get_pipeline_overview()


def set_pipeline_config(store: PipelineStore, service: str, gates_required: dict[str, list[str]]) -> dict:
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}
    result = store.set_gates_config(service=service, gates_required=gates_required)
    return {"updated": True, "service": service, "pipeline": result}


# ── GitHub API helpers ────────────────────────────────────────────────────── #

def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _create_pr(
    github_token: str,
    github_org: str,
    repo: str,
    source_branch: str,
    target_branch: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    if not github_token or not github_org:
        return {"success": False, "unavailable": True, "error": "github not configured"}
    repo_slug = repo if "/" in repo else f"{github_org}/{repo}"
    url = f"https://api.github.com/repos/{repo_slug}/pulls"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                url,
                headers=_gh_headers(github_token),
                json={"title": title, "body": body, "head": source_branch, "base": target_branch},
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"success": True, "pr_number": data["number"], "pr_url": data["html_url"]}
        if resp.status_code == 422:
            # PR may already exist
            err = resp.json()
            if "already exists" in str(err):
                return {"success": False, "error": "PR already exists for this branch pair"}
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    except httpx.ConnectError:
        return {"success": False, "unavailable": True, "error": "github not reachable"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def _merge_pr(
    github_token: str,
    github_org: str,
    repo: str,
    pr_number: int,
    commit_message: str = "",
) -> dict[str, Any]:
    if not github_token or not github_org:
        return {"success": False, "unavailable": True, "error": "github not configured"}
    repo_slug = repo if "/" in repo else f"{github_org}/{repo}"
    url = f"https://api.github.com/repos/{repo_slug}/pulls/{pr_number}/merge"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.put(
                url,
                headers=_gh_headers(github_token),
                json={"merge_method": "merge", "commit_message": commit_message},
            )
        if resp.status_code == 200:
            data = resp.json()
            return {"success": True, "sha": data.get("sha"), "message": data.get("message")}
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    except httpx.ConnectError:
        return {"success": False, "unavailable": True, "error": "github not reachable"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def _list_open_prs(
    github_token: str,
    github_org: str,
    repo: str,
) -> dict[str, Any]:
    repo_slug = repo if "/" in repo else f"{github_org}/{repo}"
    url = f"https://api.github.com/repos/{repo_slug}/pulls"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                url,
                headers=_gh_headers(github_token),
                params={"state": "open", "per_page": 50},
            )
        if resp.status_code == 200:
            prs = [
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "url": pr["html_url"],
                    "base_branch": pr["base"]["ref"],
                    "head_branch": pr["head"]["ref"],
                    "author": pr["user"]["login"],
                    "created_at": pr["created_at"],
                }
                for pr in resp.json()
            ]
            return {"success": True, "prs": prs}
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except httpx.ConnectError:
        return {"success": False, "unavailable": True, "error": "github not reachable"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def _find_service_for_repo(store: PipelineStore, repo: str) -> str | None:
    pipelines = store.list_pipelines()
    repo_slug = repo.split("/")[-1] if "/" in repo else repo
    for p in pipelines:
        p_repo = p.get("repo", "")
        if p_repo == repo or p_repo.split("/")[-1] == repo_slug:
            return p["service"]
    return None
