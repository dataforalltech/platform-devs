"""Build a :class:`Plan` from a versioned runbook DAG.

The plan is NOT born from a free LLM (avoids the marketing agent's silent
"generic" fallback). It is derived from a versioned runbook:

1. topologically order the DAG (fails early on cycle / orphan);
2. resolve capability + risk per item via the single authority
   (:class:`CapabilityResolver`);
3. validate ``input_data`` against the task ``input_schema`` — fail early if a
   ``required`` task is missing required inputs (critique §1.4);
4. propagate ``required`` to the :class:`PlanItem` (critique §1.8);
5. stamp ``runbook_version`` on the plan.
"""

from __future__ import annotations

from typing import Any

from app.dev_agent.capability import CapabilityResolver
from app.dev_agent.models.plan import Capability, Plan, PlanItem, RiskLevel
from app.dev_agent.runbook.catalog import RunbookSpec, RunbookTaskSpec, get_runbook
from app.dev_agent.runbook.dag import topological_order


class PlanValidationError(ValueError):
    """The provided inputs do not satisfy a task's input_schema."""


def _validate_inputs(task_id: str, spec: RunbookTaskSpec, inputs: dict[str, Any]) -> None:
    """Validate ``inputs`` against ``spec.input_schema`` (minimal JSON-schema subset).

    Enforces ``required`` property presence and, for present values, basic
    JSON type checks. Raises :class:`PlanValidationError` on the first problem.
    A ``required`` task with no inputs at all and a non-empty required list is
    rejected here (fail early), before anything reaches the gateway.
    """
    schema = spec.input_schema or {}
    required_props: list[str] = list(schema.get("required", []))
    properties: dict[str, Any] = schema.get("properties", {})

    if spec.required and required_props and not inputs:
        raise PlanValidationError(
            f"task {task_id!r} is required but received no inputs "
            f"(needs: {required_props})"
        )

    missing = [prop for prop in required_props if prop not in inputs]
    if missing:
        raise PlanValidationError(
            f"task {task_id!r} missing required input(s): {missing}"
        )

    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for key, value in inputs.items():
        prop_schema = properties.get(key)
        if not prop_schema:
            continue  # unknown extra keys are tolerated
        expected = prop_schema.get("type")
        py_type = type_map.get(expected) if expected else None
        # bool is a subclass of int — guard against a bool passing "integer".
        if py_type and (
            not isinstance(value, py_type)
            or (expected in ("integer", "number") and isinstance(value, bool))
        ):
            raise PlanValidationError(
                f"task {task_id!r} input {key!r} must be {expected}, got {type(value).__name__}"
            )


class PlanBuilder:
    """Construct a :class:`Plan` from a runbook via the capability authority."""

    def __init__(self, caps: CapabilityResolver) -> None:
        self._caps = caps

    def build_from_runbook(
        self,
        *,
        runbook_id: str,
        session_id: str,
        inputs_by_task: dict[str, dict] | None = None,
        selected_tasks: set[str] | None = None,
    ) -> Plan:
        rb: RunbookSpec = get_runbook(runbook_id)
        order = topological_order(rb)  # fails early on cycle / orphan
        inputs_by_task = inputs_by_task or {}

        # Create the plan first so each item can be stamped with plan_id.
        plan = Plan(
            session_id=session_id,
            runbook_id=rb.id,
            runbook_version=rb.version,
            title=rb.name,
            summary=rb.description,
            explanation=self._render_explanation(rb, order),
            responsible_profile=rb.responsible_profile,
            items=[],
        )

        items: list[PlanItem] = []
        seq = 0
        for task_id in order:
            if selected_tasks is not None and task_id not in selected_tasks:
                continue
            spec = rb.tasks[task_id]
            inputs = inputs_by_task.get(task_id, {})
            _validate_inputs(task_id, spec, inputs)

            if spec.operation_id is not None:
                # Operation-first (ADR-009): resolve capability/risk from the
                # catalog Operation; the concrete gateway tool is resolved too.
                rec = self._caps.record_for_operation(spec.operation_id)
                if rec is None:
                    raise PlanValidationError(
                        f"operation {spec.operation_id!r} not resolvable in catalog "
                        f"(gap) for task {task_id!r}"
                    )
                cap = (Capability(spec.capability_override)
                       if spec.capability_override else Capability(rec.capability))
                risk = (RiskLevel(spec.risk_override)
                        if spec.risk_override else RiskLevel(rec.risk_level))
                tool = self._caps.tool_for_operation(spec.operation_id) or spec.operation_id
            else:
                # Legacy: bind the gateway tool directly (unchanged behaviour).
                cap = self._caps.resolve(spec.tool, override=spec.capability_override)
                risk = self._caps.classify_risk(spec.tool, cap, override=spec.risk_override)
                tool = spec.tool
            seq += 1
            items.append(
                PlanItem(
                    plan_id=plan.plan_id,
                    sequence_num=seq,
                    runbook_id=rb.id,
                    task_id=task_id,
                    depends_on=list(spec.depends_on),
                    tool=tool,
                    capability=cap,
                    risk=risk,
                    required=spec.required,
                    label=spec.title[:120],
                    description=spec.description,
                    responsible=spec.responsible,
                    input_data=inputs,
                )
            )

        plan.items = items
        return plan

    @staticmethod
    def _render_explanation(rb: RunbookSpec, order: list[str]) -> str:
        lines = [f"## {rb.name}\n", rb.description, "\n### Steps (execution order)\n"]
        for i, tid in enumerate(order, 1):
            t = rb.tasks[tid]
            dep = f" (after: {', '.join(t.depends_on)})" if t.depends_on else ""
            lines.append(f"{i}. **{t.title}** — {t.responsible}{dep}")
        return "\n".join(lines)
