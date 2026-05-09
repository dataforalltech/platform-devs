"""Tools MCP do VM allocator (Phase 2h — priority queue + preemption).

9 tools que envolvem `AllocatorStore`:
- request_vm
- get_lease
- release_lease
- extend_lease
- list_my_leases
- list_pool
- query_capacity
- get_lease_ssh_key  (Phase 2f)
- cancel_queued_request  (Phase 2h)

Cada função recebe um `AllocatorStore` (instanciado uma vez no server) e os
kwargs validados. Devolve dict serializável.
"""

from __future__ import annotations

from typing import get_args

from ..knowledge.allocator_store import (
    AllocatorStore,
    AllocatorStoreError,
    LeaseNotFound,
)
from ..models.allocator import VMRequest, VMSpecName
from ..utils.validators import require_non_empty_string

_VALID_SPECS = set(get_args(VMSpecName))
_VALID_PRIORITIES = {"low", "medium", "high"}


def _error(tool: str, e: Exception) -> dict:
    if isinstance(e, LeaseNotFound):
        return {"error": "lease_not_found", "details": str(e), "tool": tool}
    if isinstance(e, AllocatorStoreError):
        return {"error": "allocator_error", "details": str(e), "tool": tool}
    if isinstance(e, ValueError):
        return {"error": "validation_error", "details": str(e), "tool": tool}
    return {"error": "internal_error", "details": str(e), "tool": tool}


def request_vm(
    store: AllocatorStore,
    spec: str,
    duration_min: int,
    owner: str,
    exclusive: bool = False,
    priority: str = "low",
    purpose: str | None = None,
    human_approved: bool = False,
) -> dict:
    """Agente solicita capacidade. Allocator decide entre lease compartilhado,
    nova VM, fila, ou denial."""
    try:
        if spec not in _VALID_SPECS:
            raise ValueError(
                f"spec inválida: {spec!r}. Opções: {sorted(_VALID_SPECS)}"
            )
        if priority not in _VALID_PRIORITIES:
            raise ValueError(f"priority inválida: {priority!r}")
        require_non_empty_string(owner, "owner")
        if not isinstance(duration_min, int) or duration_min <= 0:
            raise ValueError("duration_min deve ser inteiro > 0")

        req = VMRequest(
            spec=spec,  # type: ignore[arg-type]
            duration_min=duration_min,
            exclusive=exclusive,
            priority=priority,  # type: ignore[arg-type]
            owner=owner,
            purpose=purpose,
            human_approved=human_approved,
        )
        decision = store.request_vm(req)
        return decision.model_dump(mode="json")
    except ValueError as e:
        return _error("request_vm", e)


def get_lease(store: AllocatorStore, lease_id: str) -> dict:
    try:
        require_non_empty_string(lease_id, "lease_id")
        lease = store.get_lease(lease_id)
        if lease is None:
            return {"found": False, "lease_id": lease_id}
        return {"found": True, "lease": lease.model_dump(mode="json")}
    except ValueError as e:
        return _error("get_lease", e)


def release_lease(store: AllocatorStore, lease_id: str, by: str | None = None) -> dict:
    try:
        require_non_empty_string(lease_id, "lease_id")
        lease = store.release_lease(lease_id, by=by)
        return {"lease": lease.model_dump(mode="json")}
    except (LeaseNotFound, AllocatorStoreError, ValueError) as e:
        return _error("release_lease", e)


def extend_lease(store: AllocatorStore, lease_id: str, additional_min: int) -> dict:
    try:
        require_non_empty_string(lease_id, "lease_id")
        if not isinstance(additional_min, int) or additional_min <= 0:
            raise ValueError("additional_min deve ser inteiro > 0")
        lease = store.extend_lease(lease_id, additional_min)
        return {"lease": lease.model_dump(mode="json")}
    except (LeaseNotFound, AllocatorStoreError, ValueError) as e:
        return _error("extend_lease", e)


def list_my_leases(
    store: AllocatorStore,
    owner: str,
    status: str | None = None,
) -> dict:
    try:
        require_non_empty_string(owner, "owner")
        leases = store.list_leases(owner=owner, status=status)
        return {
            "owner": owner,
            "status_filter": status,
            "total": len(leases),
            "leases": [lease.model_dump(mode="json") for lease in leases],
        }
    except ValueError as e:
        return _error("list_my_leases", e)


def list_pool(store: AllocatorStore) -> dict:
    snapshot = store.list_pool()
    return snapshot.model_dump(mode="json")


def get_lease_ssh_key(
    store: AllocatorStore,
    lease_id: str,
    owner: str,
) -> dict:
    """Retorna a chave privada SSH (PEM) associada à VM do lease.

    Restrições:
    - owner deve ser o titular do lease.
    - lease deve estar em status ACTIVE.
    - Chave é deletada quando o lease é liberado/expirado.

    Exemplo de uso (shell do agente):
        eval $(ssh-agent)
        echo "<private_key_pem>" | ssh-add -
        ssh ubuntu@<host> -p 22
    """
    try:
        require_non_empty_string(lease_id, "lease_id")
        require_non_empty_string(owner, "owner")
        private_pem = store.get_lease_ssh_key(lease_id=lease_id, owner=owner)
        return {
            "lease_id": lease_id,
            "key_type": "ed25519",
            "private_key_pem": private_pem,
            "warning": (
                "Esta chave será invalidada quando o lease for liberado. "
                "Guarde-a com permissão 600 (chmod 600 key.pem)."
            ),
        }
    except (LeaseNotFound, AllocatorStoreError, ValueError) as e:
        return _error("get_lease_ssh_key", e)


def query_capacity(
    store: AllocatorStore,
    spec: str,
    owner: str | None = None,
) -> dict:
    try:
        if spec not in _VALID_SPECS:
            raise ValueError(
                f"spec inválida: {spec!r}. Opções: {sorted(_VALID_SPECS)}"
            )
        result = store.query_capacity(spec, owner=owner)
        return result.model_dump(mode="json")
    except ValueError as e:
        return _error("query_capacity", e)


def cancel_queued_request(
    store: AllocatorStore,
    request_id: str,
    by: str | None = None,
) -> dict:
    """Cancela um request WAITING na fila de provisão.

    Deve ser usado quando o agente não precisa mais da VM que está aguardando
    na fila (ex.: job cancelado, timeout da fila ultrapassado).
    request_id foi retornado por request_vm quando outcome=QUEUED.
    """
    try:
        require_non_empty_string(request_id, "request_id")
        return store.cancel_queued_request(request_id, by=by)
    except (AllocatorStoreError, ValueError) as e:
        return _error("cancel_queued_request", e)
