from __future__ import annotations

import logging

from ..db.store import PipelineStore, VALID_GATE_TYPES

_log = logging.getLogger(__name__)


def add_gate_result(
    store: PipelineStore,
    service: str,
    env: str,
    gate_type: str,
    passed: bool,
    details: str | None = None,
    evaluated_by: str | None = None,
) -> dict:
    if gate_type not in VALID_GATE_TYPES:
        return {
            "error": "invalid_gate_type",
            "gate_type": gate_type,
            "valid_types": sorted(VALID_GATE_TYPES),
        }

    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}

    result = store.upsert_gate(
        service=service,
        env=env,
        gate_type=gate_type,
        passed=passed,
        details=details,
        evaluated_by=evaluated_by,
    )
    return {"gate_recorded": True, "gate": result}


def get_gate_status(store: PipelineStore, service: str, env: str) -> dict:
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}

    gates_config: dict = pipeline.get("gates_config") or {}
    required_gates = gates_config.get(env, [])
    gate_results = store.get_gates(service=service, env=env)
    gate_map = {g["gate_type"]: g for g in gate_results}

    summary = []
    all_passed = True
    missing = []

    for gate_type in required_gates:
        g = gate_map.get(gate_type)
        if g is None:
            summary.append({"gate_type": gate_type, "status": "missing", "passed": False})
            missing.append(gate_type)
            all_passed = False
        else:
            passed = bool(g["passed"])
            summary.append({
                "gate_type": gate_type,
                "status": "passed" if passed else "failed",
                "passed": passed,
                "details": g.get("details"),
                "evaluated_by": g.get("evaluated_by"),
                "evaluated_at": g.get("evaluated_at"),
            })
            if not passed:
                all_passed = False

    # Also include any extra gates that were recorded but not required
    for g in gate_results:
        if g["gate_type"] not in required_gates:
            summary.append({
                "gate_type": g["gate_type"],
                "status": "extra",
                "passed": bool(g["passed"]),
                "details": g.get("details"),
                "evaluated_by": g.get("evaluated_by"),
                "evaluated_at": g.get("evaluated_at"),
            })

    return {
        "service": service,
        "env": env,
        "can_promote": all_passed and len(missing) == 0,
        "required_gates": required_gates,
        "missing_gates": missing,
        "gates": summary,
    }


def clear_gates(store: PipelineStore, service: str, env: str) -> dict:
    pipeline = store.get_pipeline(service)
    if pipeline is None:
        return {"error": "not_found", "service": service}

    deleted = store.clear_gates(service=service, env=env)
    return {"cleared": True, "service": service, "env": env, "deleted_count": deleted}
