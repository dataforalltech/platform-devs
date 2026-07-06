"""Topological ordering of a runbook DAG (Kahn's algorithm).

Unlike the marketing agent (which declares ``depends_on`` but never orders or
validates it), this module performs a real topological sort and rejects both
cycles and orphaned ``depends_on`` edges.
"""

from __future__ import annotations

from app.dev_agent.runbook.catalog import RunbookSpec


class RunbookDAGError(ValueError):
    """Cycle or invalid edge in the runbook DAG."""


def topological_order(rb: RunbookSpec) -> list[str]:
    """Return task_ids of ``rb`` in a valid execution order (Kahn).

    Raises :class:`RunbookDAGError` on a cycle or an orphaned ``depends_on``
    (a dependency that references a non-existent task). Ties are broken
    lexicographically for deterministic output.
    """
    tasks = rb.tasks
    indeg: dict[str, int] = {tid: 0 for tid in tasks}
    adj: dict[str, list[str]] = {tid: [] for tid in tasks}

    for tid, spec in tasks.items():
        for dep in spec.depends_on:
            if dep not in tasks:
                raise RunbookDAGError(
                    f"[{rb.id}] task {tid!r} depends on {dep!r} which does not exist"
                )
            adj[dep].append(tid)
            indeg[tid] += 1

    queue = sorted(tid for tid, deg in indeg.items() if deg == 0)
    order: list[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
        queue.sort()

    if len(order) != len(tasks):
        raise RunbookDAGError(
            f"[{rb.id}] cycle detected in DAG (ordered {len(order)}/{len(tasks)} tasks)"
        )
    return order
