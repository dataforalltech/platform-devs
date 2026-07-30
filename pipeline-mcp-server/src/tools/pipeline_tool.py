from __future__ import annotations

from ..db.store import PipelineStore

# Branch mapping: source → target per promotion direction
_BRANCH_MAP: dict[str, tuple[str, str]] = {
    "dev->homol": ("develop", "homol"),
    "homol->prod": ("homol", "main"),
}

_PENDING_HUMAN_APPROVAL = "pending_human_approval"
_PENDING_EXTERNAL_EXECUTION = "pending_external_execution"
_LEGACY_PENDING_STATUSES = {_PENDING_HUMAN_APPROVAL, "waiting_approval", "pending"}


def _assess_required_gates(
    pipeline: dict,
    gate_results: list[dict],
    target_env: str,
) -> dict:
    """Avalia gates de forma fail-closed sem converter ausência em aprovação."""
    gates_config = pipeline.get("gates_config") or {}
    configured_gates = gates_config.get(target_env)
    if isinstance(configured_gates, list) and configured_gates:
        gates_configured = True
        required_gates = list(dict.fromkeys(configured_gates))
    else:
        gates_configured = False
        required_gates = []
    gate_map = {gate["gate_type"]: gate for gate in gate_results}

    missing_gates = [
        gate_type for gate_type in required_gates if gate_type not in gate_map
    ]
    failed_gates = [
        gate_type
        for gate_type in required_gates
        if gate_type in gate_map and not bool(gate_map[gate_type].get("passed"))
    ]
    gates_snapshot = {
        gate_type: (
            bool(gate_map[gate_type].get("passed")) if gate_type in gate_map else None
        )
        for gate_type in required_gates
    }

    if not gates_configured:
        status = "gates_not_configured"
    elif missing_gates:
        status = "gates_not_evaluated"
    elif failed_gates:
        status = "gates_failed"
    else:
        status = "gates_satisfied"

    return {
        "gates_configured": gates_configured,
        "gates_satisfied": status == "gates_satisfied",
        "gate_status": status,
        "required_gates": required_gates,
        "missing_gates": missing_gates,
        "failed_gates": failed_gates,
        "gates_snapshot": gates_snapshot,
    }


async def register_pipeline(
    store: PipelineStore,
    service: str,
    repo: str,
    base_branch: str = "develop",
) -> dict:
    return await store.register_pipeline(
        service=service, repo=repo, base_branch=base_branch
    )


async def get_pipeline(store: PipelineStore, service: str) -> dict:
    pipeline = await store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}
    return pipeline


async def list_pipeline(
    store: PipelineStore,
    env: str | None = None,
    status: str | None = None,
) -> dict:
    pipelines = await store.list_pipelines(env=env, status=status)
    return {
        "total": len(pipelines),
        "filters": {"env": env, "status": status},
        "pipelines": pipelines,
    }


async def promote_service(
    store: PipelineStore,
    service: str,
    from_env: str,
    to_env: str,
    promoted_by: str,
    reason: str | None = None,
) -> dict:
    """Registra uma recomendação de promoção; nunca executa a promoção."""
    promoted_by = promoted_by.strip()
    if not promoted_by:
        return {
            "error": "invalid_promoted_by",
            "can_promote": False,
            "can_recommend": False,
            "promoted": False,
            "external_action_performed": False,
        }

    pipeline = await store.get_pipeline(service)
    if pipeline is None:
        return {
            "error": "not_found",
            "service": service,
            "can_promote": False,
            "external_action_performed": False,
        }

    if pipeline.get("blocked"):
        return {
            "error": "service_blocked",
            "service": service,
            "block_reason": pipeline.get("block_reason"),
            "can_promote": False,
            "external_action_performed": False,
        }

    if pipeline.get("current_env") != from_env:
        return {
            "error": "env_mismatch",
            "service": service,
            "current_env": pipeline.get("current_env"),
            "requested_from_env": from_env,
            "can_promote": False,
            "external_action_performed": False,
        }

    direction = f"{from_env}->{to_env}"
    branch_pair = _BRANCH_MAP.get(direction)
    if branch_pair is None:
        return {
            "error": "invalid_direction",
            "direction": direction,
            "can_promote": False,
            "external_action_performed": False,
        }

    source_branch, target_branch = branch_pair
    gate_results = await store.get_gates(service, from_env)
    gate_assessment = _assess_required_gates(pipeline, gate_results, to_env)

    if not gate_assessment["gates_satisfied"]:
        return {
            "can_promote": False,
            "can_recommend": False,
            "promoted": False,
            "service": service,
            "from_env": from_env,
            "to_env": to_env,
            "status": gate_assessment["gate_status"],
            "external_action_performed": False,
            **gate_assessment,
        }

    promo_id = await store.add_promotion(
        service=service,
        from_env=from_env,
        to_env=to_env,
        promoted_by=promoted_by,
        reason=reason,
        gates_snapshot=gate_assessment["gates_snapshot"],
        deploy_ref=target_branch,
        status=_PENDING_HUMAN_APPROVAL,
    )

    return {
        "can_promote": False,
        "can_recommend": True,
        "promotion_recommended": True,
        "promoted": False,
        "service": service,
        "from_env": from_env,
        "to_env": to_env,
        "promoted_by": promoted_by,
        "promotion_id": promo_id,
        "status": _PENDING_HUMAN_APPROVAL,
        "source_branch": source_branch,
        "target_branch": target_branch,
        "pr_number": None,
        "pr_url": None,
        "external_action_performed": False,
        "message": (
            "Recomendação registrada no ledger. Um operador autorizado deve abrir/revisar "
            "a PR e executar a promoção pelo runbook canônico; o pipeline-mcp não executou "
            "nenhuma ação externa."
        ),
        **gate_assessment,
    }


async def approve_promotion(
    store: PipelineStore,
    promotion_id: int,
    approved_by: str,
) -> dict:
    """Registra uma aprovação humana; nunca faz merge, deploy ou promoção."""
    approved_by = approved_by.strip()
    if not approved_by:
        return {
            "error": "invalid_approved_by",
            "approved": False,
            "approval_recorded": False,
            "external_action_performed": False,
        }

    promotion = await store.get_promotion(promotion_id)
    if promotion is None:
        return {
            "error": "not_found",
            "promotion_id": promotion_id,
            "external_action_performed": False,
        }

    if promotion.get("status") not in _LEGACY_PENDING_STATUSES:
        return {
            "error": "invalid_status",
            "promotion_id": promotion_id,
            "current_status": promotion.get("status"),
            "message": "Somente recomendações pendentes de aprovação humana podem ser aprovadas.",
            "external_action_performed": False,
        }

    service = promotion["service"]
    pipeline = await store.get_pipeline(service)
    if pipeline is None:
        return {
            "error": "service_not_found",
            "service": service,
            "external_action_performed": False,
        }

    if pipeline.get("blocked"):
        return {
            "error": "service_blocked",
            "promotion_id": promotion_id,
            "service": service,
            "block_reason": pipeline.get("block_reason"),
            "approved": False,
            "external_action_performed": False,
        }

    if pipeline.get("current_env") != promotion.get("from_env"):
        return {
            "error": "env_mismatch",
            "promotion_id": promotion_id,
            "service": service,
            "current_env": pipeline.get("current_env"),
            "promotion_from_env": promotion.get("from_env"),
            "approved": False,
            "approval_recorded": False,
            "external_action_performed": False,
        }

    gate_results = await store.get_gates(service, promotion["from_env"])
    gate_assessment = _assess_required_gates(
        pipeline, gate_results, promotion["to_env"]
    )
    if not gate_assessment["gates_satisfied"]:
        return {
            "approved": False,
            "approval_recorded": False,
            "promotion_id": promotion_id,
            "service": service,
            "status": gate_assessment["gate_status"],
            "external_action_performed": False,
            **gate_assessment,
        }

    recorded = await store.approve_promotion(
        promotion_id=promotion_id, approved_by=approved_by
    )

    return {
        "approved": True,
        "approval_recorded": True,
        "promotion_id": promotion_id,
        "service": service,
        "from_env": promotion["from_env"],
        "to_env": promotion["to_env"],
        "approved_by": approved_by,
        "status": recorded.get("status") if recorded else _PENDING_EXTERNAL_EXECUTION,
        "promoted": False,
        "merge_sha": None,
        "external_action_performed": False,
        "message": (
            "Aprovação humana registrada no ledger. Merge, build, deploy e atualização "
            "de ambiente continuam pendentes de um operador autorizado e de evidência externa."
        ),
        **gate_assessment,
    }


async def watch_prs(
    store: PipelineStore,
    repos: list[str] | None = None,
) -> dict:
    """Recomenda revisão humana usando apenas dados do ledger; não consulta GitHub."""
    pipelines = await store.list_pipelines()
    requested_repos = set(repos or [])
    if requested_repos:
        pipelines = [
            pipeline
            for pipeline in pipelines
            if pipeline.get("repo") in requested_repos
        ]

    recommendations: list[dict] = []
    for pipeline in pipelines:
        service = pipeline["service"]
        gate_results = await store.get_gates(service, "dev")
        gate_assessment = _assess_required_gates(pipeline, gate_results, "dev")
        blocked = bool(pipeline.get("blocked"))
        can_recommend = gate_assessment["gates_satisfied"] and not blocked
        if blocked:
            status = "service_blocked"
            recommended_action = "resolve_service_block_before_human_review"
        elif can_recommend:
            status = _PENDING_HUMAN_APPROVAL
            recommended_action = "human_review_required"
        else:
            status = gate_assessment["gate_status"]
            recommended_action = "complete_or_fix_gates_before_human_review"
        recommendations.append(
            {
                "service": service,
                "repo": pipeline.get("repo"),
                "pr_state": "not_observed",
                "status": status,
                "can_recommend": can_recommend,
                "recommended_action": recommended_action,
                **gate_assessment,
            }
        )

    registered_repos = {pipeline.get("repo") for pipeline in pipelines}
    unregistered_repos = sorted(
        repo for repo in requested_repos if repo not in registered_repos
    )

    waiting_human = [
        recommendation
        for recommendation in recommendations
        if recommendation["status"] == _PENDING_HUMAN_APPROVAL
    ]

    return {
        "ledger_only": True,
        "external_action_performed": False,
        "external_query_performed": False,
        "repos_assessed": len(recommendations),
        "repos_checked": 0,
        "prs_observed": 0,
        "auto_approved_count": 0,
        "auto_merged_count": 0,
        "waiting_human_count": len(waiting_human),
        "auto_approved": [],
        "waiting_human": waiting_human,
        "recommendations": recommendations,
        "unregistered_repos": unregistered_repos,
        "errors": [],
        "message": (
            "Nenhum PR foi consultado, aprovado ou mesclado. As recomendações usam "
            "somente gates registrados no ledger e exigem verificação humana externa."
        ),
    }


async def block_service(
    store: PipelineStore, service: str, reason: str, blocked_by: str
) -> dict:
    pipeline = await store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}
    result = await store.block_pipeline(
        service=service, reason=reason, blocked_by=blocked_by
    )
    return {"blocked": True, "service": service, "pipeline": result}


async def rollback(
    store: PipelineStore,
    service: str,
    env: str,
    to_version: str,
    rolled_back_by: str,
    reason: str | None = None,
) -> dict:
    rolled_back_by = rolled_back_by.strip()
    if not rolled_back_by:
        return {
            "error": "invalid_rolled_back_by",
            "rollback_requested": False,
            "rolled_back": False,
            "external_action_performed": False,
        }

    pipeline = await store.get_pipeline(service)
    if pipeline is None:
        return {
            "error": "not_found",
            "service": service,
            "external_action_performed": False,
        }

    if pipeline.get("current_env") != env:
        return {
            "error": "env_mismatch",
            "service": service,
            "current_env": pipeline.get("current_env"),
            "requested_env": env,
            "rolled_back": False,
            "external_action_performed": False,
        }

    promo_id = await store.add_promotion(
        service=service,
        from_env=env,
        to_env="rollback",
        promoted_by=rolled_back_by,
        reason=reason or f"Rollback to {to_version}",
        gates_snapshot={},
        deploy_ref=to_version,
        status=_PENDING_HUMAN_APPROVAL,
    )
    return {
        "rollback_requested": True,
        "rolled_back": False,
        "service": service,
        "env": env,
        "to_version": to_version,
        "rolled_back_by": rolled_back_by,
        "promotion_id": promo_id,
        "status": _PENDING_HUMAN_APPROVAL,
        "external_action_performed": False,
        "message": (
            "Solicitação de rollback registrada no ledger. Um operador autorizado deve "
            "executar e comprovar o rollback fora do pipeline-mcp."
        ),
    }


async def get_promotion_history(
    store: PipelineStore, service: str | None = None, limit: int = 20
) -> dict:
    history = await store.get_promotion_history(service=service, limit=limit)
    return {
        "total": len(history),
        "service": service,
        "limit": limit,
        "promotions": history,
    }


async def get_pipeline_overview(store: PipelineStore) -> dict:
    return await store.get_pipeline_overview()


async def set_pipeline_config(
    store: PipelineStore, service: str, gates_required: dict[str, list[str]]
) -> dict:
    pipeline = await store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}
    result = await store.set_gates_config(
        service=service, gates_required=gates_required
    )
    return {"updated": True, "service": service, "pipeline": result}
