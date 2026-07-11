"""AllocatorStore — VM allocator 100% sobre o ORM canônico (``platform_database.orm``).

Reescrito do ``sqlite3`` cru para o **Repository** de alto nível + **UnitOfWork**
(transações multi-statement atômicas), ligado ao pool **do tenant** (resolvido
credencial-zero via ``for_tenant``/``get_pool_for_tenant``, ORM-H-12). Roda dual-db: o
mesmo código serve MySQL (banco-por-tenant) e PostgreSQL (schema-por-tenant) — o dialeto
do pool decide o SQL.

**Tenant-scoped** (decisão de tenancy): antes o pool de VMs era GLOBAL e o ``tenant_id``
era descartado; agora cada tenant tem seu PRÓPRIO pool de VMs (isolamento MT-10), como o
padrão canônico exige. O store recebe uma ``TenantSession`` e é construído por-request.

Sem SQL manual: cada read/write cai no Repository (``find``/``insert``/``update_where``/
``delete_where``). As seções que o SQLite fazia num ``BEGIN…COMMIT`` explícito (release +
terminate + delete-key; preemption; gc; provision) rodam num ``UnitOfWork`` (uma conexão,
uma transação, commit/rollback automático) — atomicidade preservada. O único DELETE
(``vm_keys``) vira **soft-delete** canônico (``delete_where``/``excluded=1``): a leitura
filtra ``excluded=0``, então a chave "some"; ``vm_id`` é ``uuid`` (nunca reusado), logo não
há reativação acidental.

As agregações com ``status IN (...)``/subquery/``NOT EXISTS`` (cost cap, quota por owner,
seleção de preempção, VM compatível, GC) são computadas em **Python** sobre ``find().rows()``
— o pool é pequeno (cost-capped), o que mantém o orm-lint ``--strict`` limpo e evita
GROUP BY/subquery no IR (mesma filosofia do piloto pipeline-mcp).

Concorrência: o ``threading.RLock`` in-process foi removido. A atomicidade multi-statement
é garantida pelo ``UnitOfWork``. As decisões *read-then-write* de admission control (cost
cap, quota, seleção de preempção) NÃO tomam lock de linha (``SELECT … FOR UPDATE``) — em DB
compartilhado entre réplicas isso é um TOCTOU conhecido; endurecer com advisory-lock
tenant-scoped é follow-up dedicado (fora do escopo desta migração de dados).

Bridge thread→loop: os callbacks do ``TerraformProvisioner`` chegam de uma thread daemon;
como o store é async, eles são agendados no event loop via ``run_coroutine_threadsafe`` e
reconciliam o estado abrindo uma NOVA ``for_tenant`` (a sessão do request já pode ter
fechado). O ``ImmediateProvisioner`` (default/testes) chama os callbacks de forma síncrona
na thread do loop — nesse caso o resultado é aplicado inline (awaited) dentro da própria
chamada, preservando o "lease vira ACTIVE imediatamente".

Convenções: ``PLATFORM_CONVENTIONS`` (soft-delete ``excluded=0``, auditoria
``id_user_*``/``timestamp_refresh``). Como ``id_user_created`` é NOT NULL sem default, todo
write carimba o usuário-sistema (``_SYSTEM_USER``); o ``owner`` de negócio segue em coluna
própria.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from platform_database.orm import Repository, Sort, SortDirection, for_tenant
from platform_database.orm.dialects import dialect_for_pool
from platform_database.unit_of_work import UnitOfWork

from ..models.allocator import (
    HUMAN_APPROVAL_REQUIRED_SPECS,
    SPEC_COST_USD_PER_HOUR,
    AllocationDecision,
    CapacityResponse,
    VMInfo,
    VMLease,
    VMPoolSnapshot,
    VMRequest,
    lease_expiration,
    now_utc,
)
from ..models.rows import LeaseRow, QueuedRequestRow, VmKeyRow, VmRow
from ..utils.logger import get_logger
from .provisioner import ImmediateProvisioner, Provisioner
from .schema import LEASES_TABLE, QUEUED_TABLE, VM_KEYS_TABLE, VMS_TABLE

_log = get_logger(__name__)

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
# O ator de negócio real (owner) viaja em coluna própria.
_SYSTEM_USER = 0

_ACTIVE_STATES = ("PENDING", "ACTIVE")


# --------------------------------------------------------------------- #
# Erros                                                                  #
# --------------------------------------------------------------------- #
class AllocatorStoreError(ValueError):
    """Erro de operação do allocator."""


class LeaseNotFound(AllocatorStoreError):
    """Lease com id informado não existe."""


# --------------------------------------------------------------------- #
# Policy (hard stops)                                                    #
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class AllocatorPolicy:
    """Configuração de hard stops do allocator."""

    max_cost_usd_per_hour: float = 5.0
    max_active_leases_per_owner: int = 3
    max_lease_duration_min: int = 24 * 60  # 24h
    max_extensions_per_lease: int = 3
    spec_whitelist_no_approval: frozenset[str] = frozenset({"cpu-small", "cpu-medium", "cpu-large"})


# --------------------------------------------------------------------- #
# Helpers de serialização datetime ↔ TEXT ISO-8601                      #
# --------------------------------------------------------------------- #
def _dt_to_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _str_to_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _now_str() -> str:
    return now_utc().isoformat()


def _as_dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value))


def _opt_dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _lease_from_row(row: dict[str, Any]) -> VMLease:
    return VMLease(
        lease_id=row["lease_id"],
        vm_id=row["vm_id"],
        spec=row["spec"],
        owner=row["owner"],
        purpose=row["purpose"],
        status=row["status"],
        exclusive=bool(row["exclusive"]),
        priority=row["priority"],
        created_at=_as_dt(row["created_at"]),
        expires_at=_as_dt(row["expires_at"]),
        released_at=_opt_dt(row.get("released_at")),
        extension_count=int(row["extension_count"]),
        connection_hint=row.get("connection_hint"),
    )


# --------------------------------------------------------------------- #
# Store                                                                  #
# --------------------------------------------------------------------- #
class AllocatorStore:
    """VM allocator tenant-scoped sobre o ORM canônico (dual-db, async).

    Construído por-request de uma ``TenantSession`` (``for_tenant``). O provisioner, a
    policy e o segredo Fernet vêm do server (nível de processo) — só o acesso a dados é
    tenant-scoped.
    """

    def __init__(
        self,
        session: Any,
        *,
        provisioner: Provisioner | None = None,
        policy: AllocatorPolicy | None = None,
        fernet_key: bytes | None = None,
        tf_modules_root: Path | None = None,
        provision_timeout_sec: int = 300,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.policy = policy or AllocatorPolicy()
        self._provisioner: Provisioner = provisioner or ImmediateProvisioner()
        self._tf_modules_root = tf_modules_root
        self._provision_timeout_sec = provision_timeout_sec

        # Fernet key para decifrar chaves SSH privadas por VM.
        if fernet_key is not None:
            self._fernet_key: bytes = fernet_key
        else:
            from .ssh_key import generate_fernet_key  # noqa: PLC0415

            self._fernet_key = generate_fernet_key()
            _log.warning(
                "lease_secret_not_configured",
                extra={
                    "extras": {
                        "action": "ssh_keys_ephemeral",
                        "impact": "chaves SSH perdidas em restart; definir INFRA_LEASE_SECRET",
                    }
                },
            )

        # Sessão do tenant + pool (para UnitOfWork) + dialeto (para repos transacionais).
        self._session = session
        self._pool = session._pool
        self._tenant_id: str = session.tenant_id
        self._dialect = dialect_for_pool(self._pool)

        # Repositórios não-transacionais (reads + writes simples).
        self._vms = session.repository(VmRow, table_name=VMS_TABLE)
        self._leases = session.repository(LeaseRow, table_name=LEASES_TABLE)
        self._vm_keys = session.repository(VmKeyRow, table_name=VM_KEYS_TABLE)
        self._queued = session.repository(QueuedRequestRow, table_name=QUEUED_TABLE)

        # Bridge thread→loop dos callbacks do provisioner.
        self._owner_thread = threading.current_thread()
        self._loop: asyncio.AbstractEventLoop | None
        try:
            self._loop = loop or asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - construção fora de loop
            self._loop = None

    # ------------------------------------------------------------------ #
    # UnitOfWork — repos ligados a UMA transação compartilhada            #
    # ------------------------------------------------------------------ #
    def _uow_repos(self, uow: Any) -> tuple[Any, Any, Any]:
        """(vms, leases, vm_keys) ligados ao ``UnitOfWork`` — dialeto explícito
        (ORM-H-08) porque ``dialect_for_pool`` não conhece o UoW."""
        vms = Repository(uow, VmRow, table_name=VMS_TABLE, dialect=self._dialect, require_tenant=False)
        leases = Repository(
            uow, LeaseRow, table_name=LEASES_TABLE, dialect=self._dialect, require_tenant=False
        )
        keys = Repository(
            uow, VmKeyRow, table_name=VM_KEYS_TABLE, dialect=self._dialect, require_tenant=False
        )
        return vms, leases, keys

    # ------------------------------------------------------------------ #
    # Reads auxiliares (dict cru, com filtro Python p/ status IN)         #
    # ------------------------------------------------------------------ #
    async def _vm_row(self, vm_id: str) -> dict[str, Any] | None:
        rows = (await self._vms.find(where={"vm_id": vm_id}, limit=1)).rows()
        return rows[0] if rows else None

    async def _lease_row(self, lease_id: str) -> dict[str, Any] | None:
        rows = (await self._leases.find(where={"lease_id": lease_id}, limit=1)).rows()
        return rows[0] if rows else None

    async def _live_vm_rows(self) -> list[dict[str, Any]]:
        rows = (await self._vms.find()).rows()
        return [r for r in rows if r["status"] in ("PROVISIONING", "READY")]

    async def _leases_of_vm(self, vm_id: str, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
        rows = (await self._leases.find(where={"vm_id": vm_id})).rows()
        return [r for r in rows if r["status"] in statuses]

    async def _active_count_for_owner(self, owner: str) -> int:
        rows = (await self._leases.find(where={"owner": owner})).rows()
        return sum(1 for r in rows if r["status"] in _ACTIVE_STATES)

    async def _current_cost_per_hour(self) -> float:
        return sum(SPEC_COST_USD_PER_HOUR.get(r["spec"], 0.0) for r in await self._live_vm_rows())

    async def _get_vm_connection_hint(self, vm_id: str) -> str | None:
        row = await self._vm_row(vm_id)
        return row.get("connection_hint") if row else None

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #
    async def request_vm(self, request: VMRequest) -> AllocationDecision:
        await self._gc_expired()

        # 1. Approval hard stop
        denial = self._check_approval(request)
        if denial is not None:
            _log.info(
                "request_denied",
                extra={"extras": {"owner": request.owner, "spec": request.spec, "reason": denial}},
            )
            return AllocationDecision(outcome="DENIED", denial_reason=denial)

        # 2. Duration cap
        if request.duration_min > self.policy.max_lease_duration_min:
            return AllocationDecision(
                outcome="DENIED",
                denial_reason=(
                    f"duration_min={request.duration_min} excede cap "
                    f"{self.policy.max_lease_duration_min} "
                    f"(~{self.policy.max_lease_duration_min // 60}h)"
                ),
            )

        # 3. Concurrent leases per owner (PENDING + ACTIVE contam para o cap)
        active_for_owner = await self._active_count_for_owner(request.owner)
        if active_for_owner >= self.policy.max_active_leases_per_owner:
            return AllocationDecision(
                outcome="DENIED",
                denial_reason=(
                    f"owner {request.owner!r} já tem {active_for_owner} leases ativos; "
                    f"cap={self.policy.max_active_leases_per_owner}"
                ),
            )

        # 4. Try-share-first (apenas VMs READY)
        host_vm = await self._find_compatible_vm(request)
        if host_vm is not None:
            lease = await self._create_lease(
                request,
                host_vm,
                initial_status="ACTIVE",
                connection_hint=await self._get_vm_connection_hint(host_vm.vm_id),
            )
            _log.info(
                "request_leased_shared",
                extra={"extras": {"lease_id": lease.lease_id, "vm_id": host_vm.vm_id}},
            )
            return AllocationDecision(
                outcome="LEASED",
                lease=lease,
                notes=[f"Slot atribuído em VM existente {host_vm.vm_id} (compartilhado)."],
            )

        # 5. Cost cap antes de provisionar
        spec_cost = SPEC_COST_USD_PER_HOUR.get(request.spec, 0.0)
        current_cost = await self._current_cost_per_hour()
        if current_cost + spec_cost > self.policy.max_cost_usd_per_hour:
            can_provision = False
            if request.priority == "high":
                preemptable = await self._find_preemptable_vms(spec_cost)
                if preemptable:
                    async with UnitOfWork(self._pool) as uow:
                        vms, leases, keys = self._uow_repos(uow)
                        await self._preempt_vms_tx(
                            vms,
                            leases,
                            keys,
                            preemptable,
                            f"preempted by high-priority owner={request.owner!r}",
                        )
                    for vm in preemptable:
                        self._schedule_destroy(vm["vm_id"], vm["spec"])
                    if await self._current_cost_per_hour() + spec_cost <= self.policy.max_cost_usd_per_hour:
                        can_provision = True

            if not can_provision:
                waiting = [r for r in (await self._queued.find()).rows() if r["status"] == "WAITING"]
                position = len(waiting) + 1
                req_id = await self._save_queued_request(request)
                _log.info(
                    "request_queued",
                    extra={
                        "extras": {
                            "request_id": req_id,
                            "owner": request.owner,
                            "spec": request.spec,
                            "priority": request.priority,
                            "queue_position": position,
                            "current_cost": current_cost,
                            "spec_cost": spec_cost,
                        }
                    },
                )
                return AllocationDecision(
                    outcome="QUEUED",
                    queued_position=position,
                    estimated_wait_min=15 * position,
                    request_id=req_id,
                    notes=[
                        f"Provisionar {request.spec} (~${spec_cost:.2f}/h) "
                        f"junto do pool atual (${current_cost:.2f}/h) excederia cap "
                        f"${self.policy.max_cost_usd_per_hour:.2f}/h. "
                        f"request_id={req_id!r} — use cancel_queued_request para desistir."
                    ],
                )

        # 6. Provisionar nova VM (gera keypair SSH e registra em vm_keys)
        new_vm, public_key = await self._start_provisioning(request.spec)
        lease = await self._create_lease(request, new_vm, initial_status="PENDING", connection_hint=None)
        _log.info(
            "request_leased_pending",
            extra={"extras": {"lease_id": lease.lease_id, "vm_id": new_vm.vm_id, "spec": request.spec}},
        )

        # Provisiona: ImmediateProvisioner responde síncrono (aplicado inline);
        # TerraformProvisioner responde depois (bridge thread→loop).
        ready, failed = self._invoke_provisioner(request.spec, new_vm.vm_id, public_key)
        if ready is not None:
            await self._apply_vm_ready(new_vm.vm_id, ready)
        elif failed is not None:
            await self._apply_vm_failed(new_vm.vm_id, failed)

        final_row = await self._lease_row(lease.lease_id)
        final_lease = _lease_from_row(final_row) if final_row else lease
        return AllocationDecision(
            outcome="LEASED",
            lease=final_lease,
            notes=[
                f"VM {new_vm.vm_id} em provisão para {request.spec}. "
                "Use get_lease(lease_id) para verificar quando status=ACTIVE."
            ],
        )

    async def get_lease(self, lease_id: str) -> VMLease | None:
        await self._gc_expired()
        row = await self._lease_row(lease_id)
        return _lease_from_row(row) if row else None

    async def release_lease(self, lease_id: str, by: str | None = None) -> VMLease:
        await self._gc_expired()
        row = await self._lease_row(lease_id)
        if row is None:
            raise LeaseNotFound(f"lease_id {lease_id!r} não existe")
        lease = _lease_from_row(row)
        if lease.status in ("RELEASED", "EXPIRED"):
            return lease  # idempotente

        now = now_utc()
        now_str = _dt_to_str(now)

        async with UnitOfWork(self._pool) as uow:
            vms, leases, keys = self._uow_repos(uow)
            await leases.update_where(
                {"lease_id": lease_id},
                {"status": "RELEASED", "released_at": now_str},
                user_id=_SYSTEM_USER,
            )
            vm_terminated = await self._detach_lease_from_vm_tx(
                vms, leases, keys, lease_id, lease.vm_id, lease.exclusive
            )

        lease.status = "RELEASED"
        lease.released_at = now
        _log.info("lease_released", extra={"extras": {"lease_id": lease_id, "by": by}})

        if vm_terminated:
            vm_row = await self._vm_row(lease.vm_id)
            if vm_row:
                self._schedule_destroy(lease.vm_id, vm_row["spec"])

        # Capacity pode ter liberado → tenta processar fila.
        await self._provision_batch(await self._try_fulfill_queued())
        return lease

    async def extend_lease(self, lease_id: str, additional_min: int) -> VMLease:
        if additional_min <= 0:
            raise AllocatorStoreError("additional_min deve ser > 0")
        await self._gc_expired()
        row = await self._lease_row(lease_id)
        if row is None:
            raise LeaseNotFound(f"lease_id {lease_id!r} não existe")
        lease = _lease_from_row(row)
        if lease.status not in _ACTIVE_STATES:
            raise AllocatorStoreError(f"lease em status {lease.status!r} não pode ser estendido")
        if lease.extension_count >= self.policy.max_extensions_per_lease:
            raise AllocatorStoreError(
                f"lease atingiu max_extensions ({self.policy.max_extensions_per_lease})"
            )
        new_expires = lease.expires_at + timedelta(minutes=additional_min)
        total_minutes = int((new_expires - lease.created_at).total_seconds() / 60)
        if total_minutes > self.policy.max_lease_duration_min:
            raise AllocatorStoreError(
                f"extensão faria total={total_minutes}min exceder cap {self.policy.max_lease_duration_min}min"
            )
        new_ext_count = lease.extension_count + 1
        await self._leases.update_where(
            {"lease_id": lease_id},
            {"expires_at": _dt_to_str(new_expires), "extension_count": new_ext_count},
            user_id=_SYSTEM_USER,
        )
        lease.expires_at = new_expires
        lease.extension_count = new_ext_count
        _log.info(
            "lease_extended",
            extra={
                "extras": {
                    "lease_id": lease_id,
                    "added_min": additional_min,
                    "total_extensions": new_ext_count,
                }
            },
        )
        return lease

    async def list_leases(self, owner: str | None = None, status: str | None = None) -> list[VMLease]:
        await self._gc_expired()
        where: dict[str, Any] = {}
        if owner:
            where["owner"] = owner
        if status:
            where["status"] = status
        res = await self._leases.find(
            where=where or None, order_by=[Sort(column="created_at", direction=SortDirection.DESC)]
        )
        return [_lease_from_row(r) for r in res.rows()]

    async def list_pool(self) -> VMPoolSnapshot:
        await self._gc_expired()
        vm_rows = await self._live_vm_rows()
        vms = [await self._vm_info(r) for r in vm_rows]
        active_count = sum(1 for r in (await self._leases.find()).rows() if r["status"] == "ACTIVE")
        return VMPoolSnapshot(
            vms=vms,
            active_lease_count=active_count,
            total_provisioned_cost_usd_per_hour=await self._current_cost_per_hour(),
        )

    async def get_lease_ssh_key(self, lease_id: str, owner: str) -> str:
        """Retorna a chave privada SSH (PEM) associada à VM do lease.

        Exige que ``owner`` seja o titular e o lease esteja ACTIVE.
        """
        row = await self._lease_row(lease_id)
        if row is None:
            raise LeaseNotFound(f"lease_id {lease_id!r} não existe")
        lease = _lease_from_row(row)
        if lease.owner != owner:
            raise AllocatorStoreError(
                f"owner {owner!r} não é o titular do lease {lease_id!r} (titular: {lease.owner!r})"
            )
        if lease.status != "ACTIVE":
            raise AllocatorStoreError(
                f"lease {lease_id!r} em status {lease.status!r}; "
                "chave SSH disponível apenas quando status=ACTIVE"
            )
        key_rows = (await self._vm_keys.find(where={"vm_id": lease.vm_id}, limit=1)).rows()
        if not key_rows:
            raise AllocatorStoreError(
                f"Chave SSH para VM {lease.vm_id!r} não disponível. "
                "VM pode ter sido provisionada antes da Phase 2f, ou já foi terminada."
            )
        from .ssh_key import decrypt_private_key  # noqa: PLC0415

        try:
            return decrypt_private_key(bytes(key_rows[0]["encrypted_private_key"]), self._fernet_key)
        except Exception as exc:  # noqa: BLE001
            raise AllocatorStoreError(f"Falha ao decifrar chave SSH para VM {lease.vm_id!r}: {exc}") from exc

    async def query_capacity(self, spec: str, owner: str | None = None) -> CapacityResponse:
        await self._gc_expired()
        if spec in HUMAN_APPROVAL_REQUIRED_SPECS:
            return CapacityResponse(
                spec=spec,  # type: ignore[arg-type]
                can_satisfy_now=False,
                by_existing_vm=False,
                would_provision=False,
                blocked_by="approval_required",
            )
        if owner:
            active_for_owner = await self._active_count_for_owner(owner)
            if active_for_owner >= self.policy.max_active_leases_per_owner:
                return CapacityResponse(
                    spec=spec,  # type: ignore[arg-type]
                    can_satisfy_now=False,
                    by_existing_vm=False,
                    would_provision=False,
                    blocked_by="owner_concurrent_lease_cap",
                )
        fake_req = VMRequest(
            spec=spec,  # type: ignore[arg-type]
            duration_min=60,
            owner=owner or "_capacity_query",
        )
        host_vm = await self._find_compatible_vm(fake_req)
        if host_vm is not None:
            return CapacityResponse(
                spec=spec,  # type: ignore[arg-type]
                can_satisfy_now=True,
                by_existing_vm=True,
                would_provision=False,
            )
        new_cost = await self._current_cost_per_hour() + SPEC_COST_USD_PER_HOUR.get(spec, 0.0)
        if new_cost > self.policy.max_cost_usd_per_hour:
            return CapacityResponse(
                spec=spec,  # type: ignore[arg-type]
                can_satisfy_now=False,
                by_existing_vm=False,
                would_provision=False,
                blocked_by="cost_cap",
            )
        return CapacityResponse(
            spec=spec,  # type: ignore[arg-type]
            can_satisfy_now=True,
            by_existing_vm=False,
            would_provision=True,
        )

    async def cancel_queued_request(self, request_id: str, by: str | None = None) -> dict:
        """Cancela um request WAITING na fila."""
        rows = (await self._queued.find(where={"request_id": request_id}, limit=1)).rows()
        if not rows:
            raise AllocatorStoreError(f"queued request {request_id!r} não existe")
        if rows[0]["status"] != "WAITING":
            raise AllocatorStoreError(
                f"queued request {request_id!r} não está em status WAITING "
                f"(status atual: {rows[0]['status']!r})"
            )
        await self._queued.update_where(
            {"request_id": request_id}, {"status": "CANCELLED"}, user_id=_SYSTEM_USER
        )
        _log.info("queued_request_cancelled", extra={"extras": {"request_id": request_id, "by": by}})
        return {"cancelled": True, "request_id": request_id}

    # ------------------------------------------------------------------ #
    # Provisioner: invocação + bridge thread→loop                         #
    # ------------------------------------------------------------------ #
    def _invoke_provisioner(self, spec: str, vm_id: str, public_key: str) -> tuple[str | None, str | None]:
        """Chama o provisioner. Retorna ``(ready_hint, failed_err)`` quando o provisioner é
        SÍNCRONO (Immediate, callbacks na thread do loop); ``(None, None)`` quando é
        assíncrono (Terraform, thread daemon) — nesse caso os callbacks reconciliam depois
        via ``run_coroutine_threadsafe``.
        """
        outcome: dict[str, str] = {}

        def on_ready(hint: str) -> None:
            if threading.current_thread() is self._owner_thread:
                outcome["ready"] = hint
            else:
                self._bridge(self._reconcile_vm_ready(vm_id, hint))

        def on_failed(err: str) -> None:
            if threading.current_thread() is self._owner_thread:
                outcome["failed"] = err
            else:
                self._bridge(self._reconcile_vm_failed(vm_id, err))

        self._provisioner.provision(
            spec=spec,
            vm_id=vm_id,
            modules_root=self._tf_modules_root,
            timeout_sec=self._provision_timeout_sec,
            on_ready=on_ready,
            on_failed=on_failed,
            extra_tf_vars={"ssh_public_key": public_key},
        )
        return outcome.get("ready"), outcome.get("failed")

    def _bridge(self, coro: Any) -> None:
        """Agenda uma corrotina de reconciliação no event loop a partir de uma thread daemon."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:  # pragma: no cover - sem loop (não deveria ocorrer em runtime)
            coro.close()

    async def _reconcile_vm_ready(self, vm_id: str, hint: str) -> None:
        """Reabre uma sessão do tenant (a do request pode ter fechado) e aplica o READY."""
        async with for_tenant(self._tenant_id) as session:
            store = self._child_store(session)
            await store._apply_vm_ready(vm_id, hint)

    async def _reconcile_vm_failed(self, vm_id: str, error: str) -> None:
        async with for_tenant(self._tenant_id) as session:
            store = self._child_store(session)
            await store._apply_vm_failed(vm_id, error)

    def _child_store(self, session: Any) -> AllocatorStore:
        return AllocatorStore(
            session,
            provisioner=self._provisioner,
            policy=self.policy,
            fernet_key=self._fernet_key,
            tf_modules_root=self._tf_modules_root,
            provision_timeout_sec=self._provision_timeout_sec,
            loop=self._loop,
        )

    async def _provision_batch(self, to_provision: list[tuple[VMInfo, str, VMRequest]]) -> None:
        """Provisiona (fora de qualquer transação) os requests que a fila liberou."""
        for new_vm, pub_key, queued_req in to_provision:
            ready, failed = self._invoke_provisioner(queued_req.spec, new_vm.vm_id, pub_key)
            if ready is not None:
                await self._apply_vm_ready(new_vm.vm_id, ready)
            elif failed is not None:
                await self._apply_vm_failed(new_vm.vm_id, failed)

    # ------------------------------------------------------------------ #
    # Aplicação dos callbacks (READY / FAILED) — transacional             #
    # ------------------------------------------------------------------ #
    async def _apply_vm_ready(self, vm_id: str, connection_hint: str) -> None:
        """VM provisionada: READY + leases PENDING→ACTIVE + exclusive lock (atômico)."""
        async with UnitOfWork(self._pool) as uow:
            vms, leases, _keys = self._uow_repos(uow)
            await vms.update_where(
                {"vm_id": vm_id},
                {"status": "READY", "connection_hint": connection_hint},
                user_id=_SYSTEM_USER,
            )
            vm_leases = (await leases.find(where={"vm_id": vm_id})).rows()
            for r in vm_leases:
                if r["status"] == "PENDING":
                    await leases.update_where(
                        {"lease_id": r["lease_id"]},
                        {"status": "ACTIVE", "connection_hint": connection_hint},
                        user_id=_SYSTEM_USER,
                    )
            exclusive = next(
                (r for r in vm_leases if r["exclusive"] and r["status"] in ("PENDING", "ACTIVE")),
                None,
            )
            if exclusive is not None:
                await vms.update_where(
                    {"vm_id": vm_id},
                    {"exclusive_locked_by": exclusive["lease_id"]},
                    user_id=_SYSTEM_USER,
                )

        _log.info("vm_ready", extra={"extras": {"vm_id": vm_id, "connection_hint": connection_hint}})
        await self._provision_batch(await self._try_fulfill_queued())

    async def _apply_vm_failed(self, vm_id: str, error: str) -> None:
        """Provisão falhou: termina VM + expira leases PENDING + apaga chave (atômico)."""
        vm_row = await self._vm_row(vm_id)
        spec = vm_row["spec"] if vm_row else None
        now_str = _dt_to_str(now_utc())

        async with UnitOfWork(self._pool) as uow:
            vms, leases, keys = self._uow_repos(uow)
            await vms.update_where({"vm_id": vm_id}, {"status": "TERMINATED"}, user_id=_SYSTEM_USER)
            pending = [
                r for r in (await leases.find(where={"vm_id": vm_id})).rows() if r["status"] == "PENDING"
            ]
            for r in pending:
                await leases.update_where(
                    {"lease_id": r["lease_id"]},
                    {"status": "EXPIRED", "released_at": now_str},
                    user_id=_SYSTEM_USER,
                )
            await keys.delete_where({"vm_id": vm_id}, user_id=_SYSTEM_USER)

        _log.error("vm_provision_failed", extra={"extras": {"vm_id": vm_id, "error": error[:500]}})
        if spec is not None:
            self._schedule_destroy(vm_id, spec)
        await self._provision_batch(await self._try_fulfill_queued())

    # ------------------------------------------------------------------ #
    # Destroy                                                              #
    # ------------------------------------------------------------------ #
    def _schedule_destroy(self, vm_id: str, spec: str) -> None:
        """Dispara destruição assíncrona do recurso cloud via provisioner.

        Os callbacks de destroy só logam (não tocam o DB) — sem bridge necessário.
        """
        self._provisioner.destroy(
            spec=spec,
            vm_id=vm_id,
            modules_root=self._tf_modules_root,
            timeout_sec=self._provision_timeout_sec,
            on_done=lambda: _log.info(
                "vm_destroy_complete", extra={"extras": {"vm_id": vm_id, "spec": spec}}
            ),
            on_failed=lambda err: _log.error(
                "vm_destroy_failed",
                extra={
                    "extras": {
                        "vm_id": vm_id,
                        "spec": spec,
                        "error": err[:500],
                        "action": "manual_destroy_required",
                    }
                },
            ),
        )

    # ------------------------------------------------------------------ #
    # Helpers de domínio                                                   #
    # ------------------------------------------------------------------ #
    def _check_approval(self, request: VMRequest) -> str | None:
        if request.spec in HUMAN_APPROVAL_REQUIRED_SPECS and not request.human_approved:
            return (
                f"spec {request.spec!r} exige aprovação humana out-of-band. "
                "Setar request.human_approved=True após aprovação registrada."
            )
        if request.spec not in self.policy.spec_whitelist_no_approval and not request.human_approved:
            return (
                f"spec {request.spec!r} não está na whitelist sem-aprovação "
                f"({sorted(self.policy.spec_whitelist_no_approval)}). "
                "Marcar human_approved=True após registro."
            )
        return None

    async def _vm_info(self, row: dict[str, Any]) -> VMInfo:
        active = await self._leases_of_vm(row["vm_id"], _ACTIVE_STATES)
        return VMInfo(
            vm_id=row["vm_id"],
            spec=row["spec"],
            status=row["status"],
            created_at=_as_dt(row["created_at"]),
            lease_ids=[r["lease_id"] for r in active],
            exclusive_locked_by=row.get("exclusive_locked_by"),
        )

    async def _find_compatible_vm(self, request: VMRequest) -> VMInfo | None:
        """VM READY com capacidade (exclusivo → 0 leases; compartilhado → < 4)."""
        candidates = [
            r
            for r in (await self._vms.find(where={"spec": request.spec})).rows()
            if r["status"] == "READY" and r.get("exclusive_locked_by") is None
        ]
        candidates.sort(key=lambda r: str(r["created_at"]))
        for row in candidates:
            active = await self._leases_of_vm(row["vm_id"], _ACTIVE_STATES)
            if request.exclusive:
                if len(active) == 0:
                    return await self._vm_info(row)
            elif len(active) < 4:
                return await self._vm_info(row)
        return None

    async def _start_provisioning(self, spec: str) -> tuple[VMInfo, str]:
        """Registra VM PROVISIONING + keypair SSH (vm + vm_keys atômicos)."""
        from .ssh_key import encrypt_private_key, generate_keypair  # noqa: PLC0415

        vm_id = f"vm-{uuid.uuid4().hex[:10]}"
        now = now_utc()
        now_str = _dt_to_str(now)
        private_pem, public_openssh = generate_keypair()
        encrypted = encrypt_private_key(private_pem, self._fernet_key)

        async with UnitOfWork(self._pool) as uow:
            vms, _leases, keys = self._uow_repos(uow)
            await vms.insert(
                {"vm_id": vm_id, "spec": spec, "status": "PROVISIONING", "created_at": now_str},
                user_id=_SYSTEM_USER,
            )
            await keys.insert(
                {
                    "vm_id": vm_id,
                    "encrypted_private_key": encrypted,
                    "public_key": public_openssh,
                    "created_at": now_str,
                },
                user_id=_SYSTEM_USER,
            )
        return (
            VMInfo(
                vm_id=vm_id,
                spec=spec,  # type: ignore[arg-type]
                status="PROVISIONING",
                created_at=now,
                lease_ids=[],
                exclusive_locked_by=None,
            ),
            public_openssh,
        )

    async def _create_lease(
        self,
        request: VMRequest,
        vm: VMInfo,
        initial_status: str,
        connection_hint: str | None,
    ) -> VMLease:
        now = now_utc()
        lease_id = f"lease-{uuid.uuid4().hex[:12]}"
        expires_at = lease_expiration(now, request.duration_min)

        async with UnitOfWork(self._pool) as uow:
            vms, leases, _keys = self._uow_repos(uow)
            await leases.insert(
                {
                    "lease_id": lease_id,
                    "vm_id": vm.vm_id,
                    "spec": request.spec,
                    "owner": request.owner,
                    "purpose": request.purpose,
                    "status": initial_status,
                    "exclusive": 1 if request.exclusive else 0,
                    "priority": request.priority,
                    "created_at": _dt_to_str(now),
                    "expires_at": _dt_to_str(expires_at),
                    "extension_count": 0,
                    "connection_hint": connection_hint,
                },
                user_id=_SYSTEM_USER,
            )
            if request.exclusive and initial_status == "ACTIVE":
                # Só bloqueia se a VM já está READY (share path).
                await vms.update_where(
                    {"vm_id": vm.vm_id}, {"exclusive_locked_by": lease_id}, user_id=_SYSTEM_USER
                )

        return VMLease(
            lease_id=lease_id,
            vm_id=vm.vm_id,
            spec=request.spec,
            owner=request.owner,
            purpose=request.purpose,
            status=initial_status,  # type: ignore[arg-type]
            exclusive=request.exclusive,
            priority=request.priority,
            created_at=now,
            expires_at=expires_at,
            connection_hint=connection_hint,
        )

    async def _detach_lease_from_vm_tx(
        self,
        vms: Any,
        leases: Any,
        keys: Any,
        lease_id: str,
        vm_id: str,
        is_exclusive: bool,
    ) -> bool:
        """Desvincula lease da VM dentro da transação. True se a VM foi terminada."""
        if is_exclusive:
            vm_rows = (await vms.find(where={"vm_id": vm_id})).rows()
            if vm_rows and vm_rows[0].get("exclusive_locked_by") == lease_id:
                await vms.update_where({"vm_id": vm_id}, {"exclusive_locked_by": None}, user_id=_SYSTEM_USER)
        active = [
            r for r in (await leases.find(where={"vm_id": vm_id})).rows() if r["status"] in _ACTIVE_STATES
        ]
        if not active:
            vm_rows = (await vms.find(where={"vm_id": vm_id})).rows()
            if vm_rows and vm_rows[0]["status"] != "TERMINATED":
                await vms.update_where({"vm_id": vm_id}, {"status": "TERMINATED"}, user_id=_SYSTEM_USER)
            await keys.delete_where({"vm_id": vm_id}, user_id=_SYSTEM_USER)
            return True
        return False

    async def _gc_expired(self) -> None:
        now = now_utc()
        now_str = _dt_to_str(now)
        active_leases = [r for r in (await self._leases.find()).rows() if r["status"] in _ACTIVE_STATES]
        expired = [r for r in active_leases if _as_dt(r["expires_at"]) <= now]
        if not expired:
            return

        # VMs que ficaram órfãs após expirar os leases (cálculo em Python).
        expired_ids = {r["lease_id"] for r in expired}
        remaining_active_by_vm: dict[str, int] = {}
        for r in active_leases:
            if r["lease_id"] in expired_ids:
                continue
            remaining_active_by_vm[r["vm_id"]] = remaining_active_by_vm.get(r["vm_id"], 0) + 1
        orphan_vms = [r for r in await self._live_vm_rows() if remaining_active_by_vm.get(r["vm_id"], 0) == 0]

        async with UnitOfWork(self._pool) as uow:
            vms, leases, keys = self._uow_repos(uow)
            for r in expired:
                await leases.update_where(
                    {"lease_id": r["lease_id"]},
                    {"status": "EXPIRED", "released_at": now_str},
                    user_id=_SYSTEM_USER,
                )
                if r["exclusive"]:
                    vm_rows = (await vms.find(where={"vm_id": r["vm_id"]})).rows()
                    if vm_rows and vm_rows[0].get("exclusive_locked_by") == r["lease_id"]:
                        await vms.update_where(
                            {"vm_id": r["vm_id"]},
                            {"exclusive_locked_by": None},
                            user_id=_SYSTEM_USER,
                        )
                _log.info("lease_expired_gc", extra={"extras": {"lease_id": r["lease_id"]}})
            for vm in orphan_vms:
                await vms.update_where({"vm_id": vm["vm_id"]}, {"status": "TERMINATED"}, user_id=_SYSTEM_USER)
                await keys.delete_where({"vm_id": vm["vm_id"]}, user_id=_SYSTEM_USER)

        for vm in orphan_vms:
            self._schedule_destroy(vm["vm_id"], vm["spec"])

    async def _save_queued_request(self, request: VMRequest) -> str:
        """Persiste request na fila WAITING. Retorna o ``request_id`` gerado."""
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        await self._queued.insert(
            {
                "request_id": request_id,
                "spec": request.spec,
                "duration_min": request.duration_min,
                "owner": request.owner,
                "purpose": request.purpose,
                "exclusive": 1 if request.exclusive else 0,
                "priority": request.priority,
                "human_approved": 1 if request.human_approved else 0,
                "created_at": _now_str(),
                "status": "WAITING",
            },
            user_id=_SYSTEM_USER,
        )
        return request_id

    # ------------------------------------------------------------------ #
    # Fila + preemption                                                    #
    # ------------------------------------------------------------------ #
    async def _find_preemptable_vms(self, spec_cost: float) -> list[dict[str, Any]]:
        """Conjunto mínimo de VMs READY com APENAS leases low-priority p/ liberar orçamento.

        Greedy: VMs mais caras primeiro até cobrir o déficit. Vazio se não dá p/ liberar.
        """
        current_cost = await self._current_cost_per_hour()
        deficit = (current_cost + spec_cost) - self.policy.max_cost_usd_per_hour
        if deficit <= 0:
            return []

        candidates: list[dict[str, Any]] = []
        for vm in (await self._vms.find(where={"status": "READY"})).rows():
            active = await self._leases_of_vm(vm["vm_id"], _ACTIVE_STATES)
            if not active:
                continue
            if all(r["priority"] == "low" for r in active):
                candidates.append(vm)
        if not candidates:
            return []

        candidates.sort(key=lambda r: SPEC_COST_USD_PER_HOUR.get(r["spec"], 0.0), reverse=True)
        selected: list[dict[str, Any]] = []
        freed = 0.0
        for vm in candidates:
            selected.append(vm)
            freed += SPEC_COST_USD_PER_HOUR.get(vm["spec"], 0.0)
            if freed >= deficit:
                break
        return selected if freed >= deficit else []

    async def _preempt_vms_tx(
        self, vms: Any, leases: Any, keys: Any, targets: list[dict[str, Any]], reason: str
    ) -> None:
        """RELEASED em todos os leases + TERMINATED nas VMs + apaga chaves (dentro da tx)."""
        now_str = _dt_to_str(now_utc())
        for vm in targets:
            vm_id = vm["vm_id"]
            active = [
                r for r in (await leases.find(where={"vm_id": vm_id})).rows() if r["status"] in _ACTIVE_STATES
            ]
            for r in active:
                await leases.update_where(
                    {"lease_id": r["lease_id"]},
                    {"status": "RELEASED", "released_at": now_str},
                    user_id=_SYSTEM_USER,
                )
            await vms.update_where(
                {"vm_id": vm_id},
                {"status": "TERMINATED", "exclusive_locked_by": None},
                user_id=_SYSTEM_USER,
            )
            await keys.delete_where({"vm_id": vm_id}, user_id=_SYSTEM_USER)
            _log.warning(
                "vm_preempted",
                extra={"extras": {"vm_id": vm_id, "spec": vm["spec"], "reason": reason}},
            )

    async def _try_fulfill_queued(self) -> list[tuple[VMInfo, str, VMRequest]]:
        """Processa requests WAITING que possam ser atendidos agora.

        Retorna a lista de ``(VMInfo, public_key, VMRequest)`` para provisionar FORA de
        transação. Requests atendidos por share de VM existente são FULFILLED direto.
        Ordena por prioridade (high→medium→low) e depois created_at ASC (FIFO por prioridade).
        """
        _priority_rank = {"high": 1, "medium": 2, "low": 3}
        waiting = [r for r in (await self._queued.find()).rows() if r["status"] == "WAITING"]
        waiting.sort(key=lambda r: (_priority_rank.get(r["priority"], 3), str(r["created_at"])))

        to_provision: list[tuple[VMInfo, str, VMRequest]] = []
        for row in waiting:
            if await self._active_count_for_owner(row["owner"]) >= self.policy.max_active_leases_per_owner:
                continue  # owner com muitos leases — pula por agora

            request = VMRequest(
                spec=row["spec"],  # type: ignore[arg-type]
                duration_min=row["duration_min"],
                owner=row["owner"],
                purpose=row["purpose"],
                exclusive=bool(row["exclusive"]),
                priority=row["priority"],  # type: ignore[arg-type]
                human_approved=bool(row["human_approved"]),
            )

            # 1. Tenta compartilhar VM existente (sem custo adicional).
            host_vm = await self._find_compatible_vm(request)
            if host_vm is not None:
                await self._queued.update_where(
                    {"request_id": row["request_id"]}, {"status": "FULFILLED"}, user_id=_SYSTEM_USER
                )
                await self._create_lease(
                    request,
                    host_vm,
                    initial_status="ACTIVE",
                    connection_hint=await self._get_vm_connection_hint(host_vm.vm_id),
                )
                _log.info(
                    "queued_request_fulfilled_shared",
                    extra={
                        "extras": {
                            "request_id": row["request_id"],
                            "vm_id": host_vm.vm_id,
                            "owner": row["owner"],
                        }
                    },
                )
                continue

            # 2. Precisa de nova VM — verifica cost cap.
            spec_cost = SPEC_COST_USD_PER_HOUR.get(row["spec"], 0.0)
            if await self._current_cost_per_hour() + spec_cost > self.policy.max_cost_usd_per_hour:
                continue  # ainda não cabe no orçamento

            # 3. Provisiona nova VM.
            await self._queued.update_where(
                {"request_id": row["request_id"]}, {"status": "FULFILLED"}, user_id=_SYSTEM_USER
            )
            new_vm, public_key = await self._start_provisioning(request.spec)
            await self._create_lease(request, new_vm, initial_status="PENDING", connection_hint=None)
            to_provision.append((new_vm, public_key, request))
            _log.info(
                "queued_request_fulfilling_provision",
                extra={
                    "extras": {
                        "request_id": row["request_id"],
                        "vm_id": new_vm.vm_id,
                        "owner": row["owner"],
                        "spec": row["spec"],
                    }
                },
            )

        return to_provision


__all__ = [
    "AllocatorStore",
    "AllocatorStoreError",
    "LeaseNotFound",
    "AllocatorPolicy",
]
