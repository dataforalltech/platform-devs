import os
"""AllocatorStore — Phase 2h (priority queue + preemption).

Mudanças Phase 2h vs Phase 2f:

9. `queued_requests` SQLite table — persiste requests bloqueados pelo cost cap.
   - `request_vm()` salva na fila (com `request_id`) quando cost cap impede nova VM.
   - `cancel_queued_request(request_id)` cancela request WAITING.
   - Fila é processada em `release_lease()`, `_on_vm_ready()` e `_on_vm_failed()`.

10. Preemption (alta prioridade) — request com priority='high' que bate no cost cap
    tenta terminar VMs que têm APENAS leases de prioridade 'low', liberando orçamento.
    Seleção greedy: VMs mais caras primeiro, até caber o request.
    Se preemption não consegue liberar orçamento suficiente → cai na fila normalmente.

7. `vm_keys` SQLite table — armazena chave privada Ed25519 cifrada (Fernet) por VM.
   - `_start_provisioning()` gera keypair e insere em `vm_keys`.
   - Chave pública passada ao provisioner via `extra_tf_vars={"ssh_public_key": pubkey}`.
   - `get_lease_ssh_key(lease_id, owner)` decifra e retorna a chave privada PEM.
   - Chave deletada de `vm_keys` quando VM é terminada (`_detach_lease_from_vm_tx`,
     `_on_vm_failed`).

8. `lease_secret` (Fernet key) — derivado de `INFRA_LEASE_SECRET` (env) ou gerado
   aleatoriamente por sessão (chaves SSH perdidas em restart sem o secret configurado).

Thread-safety:
  `_schedule_destroy` pode ser chamado dentro ou fora do lock:
  - TerraformProvisioner.destroy() → spawna thread, retorna imediatamente (seguro dentro do lock).
  - ImmediateProvisioner.destroy() → chama on_done() síncrono; on_done é apenas log (seguro).
  Em `_on_vm_failed`: `_schedule_destroy` chamado FORA do lock para evitar
  chamadas aninhadas desnecessárias quando o provisioner é síncrono.
  Em `release_lease` / `_on_vm_ready` / `_on_vm_failed`: `_try_fulfill_queued_inside_lock()`
  retorna lista de (VMInfo, public_key, VMRequest) para provisionar FORA do lock.
"""

from __future__ import annotations

import psycopg2
import psycopg2.pool
import threading
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

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
from ..utils.logger import get_logger
from .provisioner import ImmediateProvisioner, Provisioner

if TYPE_CHECKING:
    pass  # evita import circular

_log = get_logger(__name__)


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
    spec_whitelist_no_approval: frozenset[str] = frozenset(
        {"cpu-small", "cpu-medium", "cpu-large"}
    )


# --------------------------------------------------------------------- #
# Helpers de serialização datetime ↔ TEXT                               #
# --------------------------------------------------------------------- #
def _dt_to_str(dt) -> str | None:  # type: ignore[no-untyped-def]
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _str_to_dt(s: str | None):  # type: ignore[no-untyped-def]
    if s is None:
        return None
    from datetime import datetime  # noqa: PLC0415
    return datetime.fromisoformat(s)


# --------------------------------------------------------------------- #
# Store                                                                  #
# --------------------------------------------------------------------- #
class AllocatorStore:
    """VM allocator persistido em SQLite com provisioner injetável (Phase 2c).

    db_path=":memory:" + provisioner=None → testes isolados (ImmediateProvisioner).
    Prod: db_path="/path/file.db" + TerraformProvisioner.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        policy: AllocatorPolicy | None = None,
        provisioner: Provisioner | None = None,
        tf_modules_root: Path | None = None,
        provision_timeout_sec: int = 300,
        lease_secret: str | None = None,
    ) -> None:
        self.policy = policy or AllocatorPolicy()
        self._db_path = db_path
        self._provisioner: Provisioner = provisioner or ImmediateProvisioner()
        self._tf_modules_root = tf_modules_root
        self._provision_timeout_sec = provision_timeout_sec
        self._lock = threading.RLock()

        # Fernet key para cifrar chaves SSH privadas por VM (Phase 2f).
        if lease_secret is not None:
            self._fernet_key: bytes = lease_secret.encode()
        else:
            from .ssh_key import generate_fernet_key  # noqa: PLC0415
            self._fernet_key = generate_fernet_key()
            _log.warning(
                "lease_secret_not_configured",
                extra={"extras": {
                    "action": "ssh_keys_ephemeral",
                    "impact": "chaves SSH perdidas em restart; definir INFRA_LEASE_SECRET",
                }},
            )

        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=os.getenv("PG_DSN", "postgresql://localhost/infra_mcp"),
        )
        self._init_schema()

    # ------------------------------------------------------------------ #
    # Connection Management                                               #
    # ------------------------------------------------------------------ #

    @contextmanager
    def _get_conn(self):
        """Get connection from pool with transaction management."""
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        if self._pool:
            self._pool.closeall()

    def __del__(self) -> None:
        try:
            if self._pool:
                self._pool.closeall()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    # Schema                                                               #
    # ------------------------------------------------------------------ #
    def _init_schema(self) -> None:
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS vms (
                vm_id                TEXT PRIMARY KEY,
                spec                 TEXT NOT NULL,
                status               TEXT NOT NULL DEFAULT 'PROVISIONING',
                created_at           TEXT NOT NULL,
                exclusive_locked_by  TEXT,
                connection_hint      TEXT
            );

            CREATE TABLE IF NOT EXISTS leases (
                lease_id        TEXT PRIMARY KEY,
                vm_id           TEXT NOT NULL REFERENCES vms(vm_id),
                spec            TEXT NOT NULL,
                owner           TEXT NOT NULL,
                purpose         TEXT,
                status          TEXT NOT NULL DEFAULT 'PENDING',
                exclusive       INTEGER NOT NULL DEFAULT 0,
                priority        TEXT NOT NULL DEFAULT 'low',
                created_at      TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                released_at     TEXT,
                extension_count INTEGER NOT NULL DEFAULT 0,
                connection_hint TEXT
            );

            -- Phase 2f: chave privada SSH cifrada por VM.
            -- Deletada quando a VM é terminada (release_lease último / _on_vm_failed).
            CREATE TABLE IF NOT EXISTS vm_keys (
                vm_id                  TEXT PRIMARY KEY REFERENCES vms(vm_id),
                encrypted_private_key  BLOB NOT NULL,
                public_key             TEXT NOT NULL,
                created_at             TEXT NOT NULL
            );

            -- Phase 2h: fila persistida de requests bloqueados pelo cost cap.
            -- status: WAITING → FULFILLED | CANCELLED
            CREATE TABLE IF NOT EXISTS queued_requests (
                request_id     TEXT PRIMARY KEY,
                spec           TEXT NOT NULL,
                duration_min   INTEGER NOT NULL,
                owner          TEXT NOT NULL,
                purpose        TEXT,
                exclusive      INTEGER NOT NULL DEFAULT 0,
                priority       TEXT NOT NULL DEFAULT 'low',
                human_approved INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'WAITING'
            );

            CREATE INDEX IF NOT EXISTS idx_leases_owner  ON leases(owner);
            CREATE INDEX IF NOT EXISTS idx_leases_vm_id  ON leases(vm_id);
            CREATE INDEX IF NOT EXISTS idx_leases_status ON leases(status);
            CREATE INDEX IF NOT EXISTS idx_queued_status ON queued_requests(status, priority, created_at);
        """)
        # Migrations idempotentes para bancos criados em fases anteriores
        for ddl in [
            "ALTER TABLE vms ADD COLUMN connection_hint TEXT",
        ]:
            try:
                self._con.execute(ddl)
            except sqlite3.OperationalError:
                pass  # coluna já existe

    # ------------------------------------------------------------------ #
    # Row → model                                                          #
    # ------------------------------------------------------------------ #
    def _row_to_lease(self, row: sqlite3.Row) -> VMLease:
        return VMLease(
            lease_id=row["lease_id"],
            vm_id=row["vm_id"],
            spec=row["spec"],
            owner=row["owner"],
            purpose=row["purpose"],
            status=row["status"],
            exclusive=bool(row["exclusive"]),
            priority=row["priority"],
            created_at=_str_to_dt(row["created_at"]),
            expires_at=_str_to_dt(row["expires_at"]),
            released_at=_str_to_dt(row["released_at"]),
            extension_count=row["extension_count"],
            connection_hint=row["connection_hint"],
        )

    def _row_to_vm(self, row: sqlite3.Row) -> VMInfo:
        active_rows = self._con.execute(
            "SELECT lease_id FROM leases WHERE vm_id = ? AND status IN ('PENDING','ACTIVE')",
            (row["vm_id"],),
        ).fetchall()
        return VMInfo(
            vm_id=row["vm_id"],
            spec=row["spec"],
            status=row["status"],
            created_at=_str_to_dt(row["created_at"]),
            lease_ids=[r["lease_id"] for r in active_rows],
            exclusive_locked_by=row["exclusive_locked_by"],
        )

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #
    def request_vm(self, request: VMRequest) -> AllocationDecision:
        with self._lock:
            self._gc_expired()

            # 1. Approval hard stop
            denial = self._check_approval(request)
            if denial is not None:
                _log.info(
                    "request_denied",
                    extra={"extras": {
                        "owner": request.owner,
                        "spec": request.spec,
                        "reason": denial,
                    }},
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
            active_for_owner: int = self._con.execute(
                "SELECT COUNT(*) FROM leases WHERE owner = ? AND status IN ('PENDING','ACTIVE')",
                (request.owner,),
            ).fetchone()[0]
            if active_for_owner >= self.policy.max_active_leases_per_owner:
                return AllocationDecision(
                    outcome="DENIED",
                    denial_reason=(
                        f"owner {request.owner!r} já tem {active_for_owner} leases ativos; "
                        f"cap={self.policy.max_active_leases_per_owner}"
                    ),
                )

            # 4. Try-share-first (apenas VMs READY)
            host_vm = self._find_compatible_vm(request)
            if host_vm is not None:
                lease = self._create_lease(
                    request, host_vm,
                    initial_status="ACTIVE",
                    connection_hint=self._get_vm_connection_hint(host_vm.vm_id),
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
            current_cost = self._current_cost_per_hour()
            if current_cost + spec_cost > self.policy.max_cost_usd_per_hour:
                # Phase 2h: preemption para requests de alta prioridade.
                # Tenta terminar VMs que têm APENAS leases low-priority para liberar orçamento.
                can_provision = False
                if request.priority == "high":
                    preemptable = self._find_preemptable_vms_inside_lock(spec_cost)
                    if preemptable:
                        self._con.execute("BEGIN")
                        try:
                            self._preempt_vms_inside_lock(
                                preemptable,
                                f"preempted by high-priority owner={request.owner!r}",
                            )
                            self._con.execute("COMMIT")
                        except Exception:
                            self._con.execute("ROLLBACK")
                            raise
                        # Destroy preempted VMs (safe dentro do lock: TF spawna thread)
                        for vm in preemptable:
                            self._schedule_destroy(vm["vm_id"], vm["spec"])
                        # Recheck após preemption
                        if (
                            self._current_cost_per_hour() + spec_cost
                            <= self.policy.max_cost_usd_per_hour
                        ):
                            can_provision = True

                if not can_provision:
                    # Sem condição de provisionar agora → persistir na fila.
                    position: int = (
                        self._con.execute(
                            "SELECT COUNT(*) FROM queued_requests WHERE status='WAITING'"
                        ).fetchone()[0]
                        + 1
                    )
                    req_id = self._save_queued_request(request)
                    _log.info(
                        "request_queued",
                        extra={"extras": {
                            "request_id": req_id,
                            "owner": request.owner,
                            "spec": request.spec,
                            "priority": request.priority,
                            "queue_position": position,
                            "current_cost": current_cost,
                            "spec_cost": spec_cost,
                        }},
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
                # can_provision=True após preemption → cai no passo 6

            # 6. Provisionar nova VM (gera keypair SSH e registra em vm_keys)
            new_vm, public_key = self._start_provisioning(request.spec)
            lease = self._create_lease(
                request, new_vm,
                initial_status="PENDING",
                connection_hint=None,
            )
            _log.info(
                "request_leased_pending",
                extra={"extras": {
                    "lease_id": lease.lease_id,
                    "vm_id": new_vm.vm_id,
                    "spec": request.spec,
                }},
            )
            # Notificar provisioner fora do lock para não bloquear outras requests.
            # ImmediateProvisioner chama on_ready de forma síncrona aqui.
            # TerraformProvisioner spawna thread e retorna imediatamente.
            lease_id = lease.lease_id
            vm_id = new_vm.vm_id

        # --- fora do lock --- #
        self._provisioner.provision(
            spec=request.spec,
            vm_id=vm_id,
            modules_root=self._tf_modules_root,
            timeout_sec=self._provision_timeout_sec,
            on_ready=lambda hint: self._on_vm_ready(vm_id, hint),
            on_failed=lambda err: self._on_vm_failed(vm_id, err),
            extra_tf_vars={"ssh_public_key": public_key},
        )

        # Re-lê lease: ImmediateProvisioner já atualizou → ACTIVE;
        # TerraformProvisioner ainda está em background → PENDING.
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            final_lease = self._row_to_lease(row) if row else lease

        return AllocationDecision(
            outcome="LEASED",
            lease=final_lease,
            notes=[
                f"VM {vm_id} em provisão para {request.spec}. "
                "Use get_lease(lease_id) para verificar quando status=ACTIVE."
            ],
        )

    def get_lease(self, lease_id: str) -> VMLease | None:
        with self._lock:
            self._gc_expired()
            row = self._con.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            return self._row_to_lease(row) if row else None

    def release_lease(self, lease_id: str, by: str | None = None) -> VMLease:
        to_provision: list[tuple[VMInfo, str, VMRequest]] = []

        with self._lock:
            self._gc_expired()
            row = self._con.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None:
                raise LeaseNotFound(f"lease_id {lease_id!r} não existe")
            lease = self._row_to_lease(row)
            if lease.status in ("RELEASED", "EXPIRED"):
                return lease  # idempotente

            now = now_utc()
            now_str = _dt_to_str(now)

            self._con.execute("BEGIN")
            try:
                self._con.execute(
                    "UPDATE leases SET status='RELEASED', released_at=? WHERE lease_id=?",
                    (now_str, lease_id),
                )
                vm_terminated = self._detach_lease_from_vm_tx(lease_id, lease.vm_id, lease.exclusive)
                self._con.execute("COMMIT")
            except Exception:
                self._con.execute("ROLLBACK")
                raise

            lease.status = "RELEASED"
            lease.released_at = now
            _log.info("lease_released", extra={"extras": {"lease_id": lease_id, "by": by}})

            if vm_terminated:
                # Lê spec da VM para passar ao destroy (safe: dentro do lock, apenas leitura)
                vm_row = self._con.execute(
                    "SELECT spec FROM vms WHERE vm_id=?", (lease.vm_id,)
                ).fetchone()
                if vm_row:
                    self._schedule_destroy(lease.vm_id, vm_row["spec"])

            # Phase 2h: capacity pode ter liberado → tenta processar fila.
            to_provision = self._try_fulfill_queued_inside_lock()

        # Provisiona requests da fila fora do lock.
        for new_vm, pub_key, queued_req in to_provision:
            self._provisioner.provision(
                spec=queued_req.spec,
                vm_id=new_vm.vm_id,
                modules_root=self._tf_modules_root,
                timeout_sec=self._provision_timeout_sec,
                on_ready=lambda hint, vid=new_vm.vm_id: self._on_vm_ready(vid, hint),
                on_failed=lambda err, vid=new_vm.vm_id: self._on_vm_failed(vid, err),
                extra_tf_vars={"ssh_public_key": pub_key},
            )

        return lease

    def extend_lease(self, lease_id: str, additional_min: int) -> VMLease:
        if additional_min <= 0:
            raise AllocatorStoreError("additional_min deve ser > 0")
        with self._lock:
            self._gc_expired()
            row = self._con.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None:
                raise LeaseNotFound(f"lease_id {lease_id!r} não existe")
            lease = self._row_to_lease(row)
            if lease.status not in ("PENDING", "ACTIVE"):
                raise AllocatorStoreError(
                    f"lease em status {lease.status!r} não pode ser estendido"
                )
            if lease.extension_count >= self.policy.max_extensions_per_lease:
                raise AllocatorStoreError(
                    f"lease atingiu max_extensions ({self.policy.max_extensions_per_lease})"
                )
            new_expires = lease.expires_at + timedelta(minutes=additional_min)
            total_minutes = int((new_expires - lease.created_at).total_seconds() / 60)
            if total_minutes > self.policy.max_lease_duration_min:
                raise AllocatorStoreError(
                    f"extensão faria total={total_minutes}min exceder cap "
                    f"{self.policy.max_lease_duration_min}min"
                )
            new_ext_count = lease.extension_count + 1
            self._con.execute(
                "UPDATE leases SET expires_at=?, extension_count=? WHERE lease_id=?",
                (_dt_to_str(new_expires), new_ext_count, lease_id),
            )
            lease.expires_at = new_expires
            lease.extension_count = new_ext_count
            _log.info(
                "lease_extended",
                extra={"extras": {
                    "lease_id": lease_id,
                    "added_min": additional_min,
                    "total_extensions": new_ext_count,
                }},
            )
            return lease

    def list_leases(
        self,
        owner: str | None = None,
        status: str | None = None,
    ) -> list[VMLease]:
        with self._lock:
            self._gc_expired()
            query = "SELECT * FROM leases WHERE 1=1"
            params: list[str] = []
            if owner:
                query += " AND owner = ?"
                params.append(owner)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            rows = self._con.execute(query, params).fetchall()
            return [self._row_to_lease(r) for r in rows]

    def list_pool(self) -> VMPoolSnapshot:
        with self._lock:
            self._gc_expired()
            vm_rows = self._con.execute(
                "SELECT * FROM vms WHERE status IN ('PROVISIONING','READY')"
            ).fetchall()
            vms = [self._row_to_vm(r) for r in vm_rows]
            active_count: int = self._con.execute(
                "SELECT COUNT(*) FROM leases WHERE status='ACTIVE'"
            ).fetchone()[0]
            return VMPoolSnapshot(
                vms=vms,
                active_lease_count=active_count,
                total_provisioned_cost_usd_per_hour=self._current_cost_per_hour(),
            )

    def get_lease_ssh_key(self, lease_id: str, owner: str) -> str:
        """Retorna a chave privada SSH (PEM) associada à VM do lease.

        Args:
            lease_id: ID do lease.
            owner: Deve corresponder ao titular do lease (autenticação mínima).

        Returns:
            String PEM com a chave privada Ed25519 para conexão SSH.

        Raises:
            LeaseNotFound: lease não existe.
            AllocatorStoreError: owner não corresponde, lease não ACTIVE,
                ou chave não disponível (VM provisionada antes da Phase 2f).
        """
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if row is None:
                raise LeaseNotFound(f"lease_id {lease_id!r} não existe")
            lease = self._row_to_lease(row)
            if lease.owner != owner:
                raise AllocatorStoreError(
                    f"owner {owner!r} não é o titular do lease {lease_id!r} "
                    f"(titular: {lease.owner!r})"
                )
            if lease.status != "ACTIVE":
                raise AllocatorStoreError(
                    f"lease {lease_id!r} em status {lease.status!r}; "
                    "chave SSH disponível apenas quando status=ACTIVE"
                )
            key_row = self._con.execute(
                "SELECT encrypted_private_key FROM vm_keys WHERE vm_id = ?",
                (lease.vm_id,),
            ).fetchone()
            if key_row is None:
                raise AllocatorStoreError(
                    f"Chave SSH para VM {lease.vm_id!r} não disponível. "
                    "VM pode ter sido provisionada antes da Phase 2f, ou já foi terminada."
                )
            from .ssh_key import decrypt_private_key  # noqa: PLC0415
            try:
                return decrypt_private_key(
                    bytes(key_row["encrypted_private_key"]), self._fernet_key
                )
            except Exception as exc:  # noqa: BLE001
                raise AllocatorStoreError(
                    f"Falha ao decifrar chave SSH para VM {lease.vm_id!r}: {exc}"
                ) from exc

    def query_capacity(self, spec: str, owner: str | None = None) -> CapacityResponse:
        with self._lock:
            self._gc_expired()
            if spec in HUMAN_APPROVAL_REQUIRED_SPECS:
                return CapacityResponse(
                    spec=spec,  # type: ignore[arg-type]
                    can_satisfy_now=False,
                    by_existing_vm=False,
                    would_provision=False,
                    blocked_by="approval_required",
                )
            if owner:
                active_for_owner: int = self._con.execute(
                    "SELECT COUNT(*) FROM leases WHERE owner=? AND status IN ('PENDING','ACTIVE')",
                    (owner,),
                ).fetchone()[0]
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
            host_vm = self._find_compatible_vm(fake_req)
            if host_vm is not None:
                return CapacityResponse(
                    spec=spec,  # type: ignore[arg-type]
                    can_satisfy_now=True,
                    by_existing_vm=True,
                    would_provision=False,
                )
            new_cost = self._current_cost_per_hour() + SPEC_COST_USD_PER_HOUR.get(spec, 0.0)
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

    # ------------------------------------------------------------------ #
    # Callbacks do provisioner (chamados de thread externa)               #
    # ------------------------------------------------------------------ #
    def _on_vm_ready(self, vm_id: str, connection_hint: str) -> None:
        """VM provisionada com sucesso: READY + leases PENDING→ACTIVE + exclusive lock."""
        to_provision: list[tuple[VMInfo, str, VMRequest]] = []

        with self._lock:
            self._con.execute("BEGIN")
            try:
                self._con.execute(
                    "UPDATE vms SET status='READY', connection_hint=? WHERE vm_id=?",
                    (connection_hint, vm_id),
                )
                # Ativa leases PENDING desta VM
                self._con.execute(
                    "UPDATE leases SET status='ACTIVE', connection_hint=? "
                    "WHERE vm_id=? AND status='PENDING'",
                    (connection_hint, vm_id),
                )
                # Se algum lease ativo é exclusivo, registrar o lock na VM
                excl = self._con.execute(
                    "SELECT lease_id FROM leases "
                    "WHERE vm_id=? AND exclusive=1 AND status='ACTIVE' LIMIT 1",
                    (vm_id,),
                ).fetchone()
                if excl:
                    self._con.execute(
                        "UPDATE vms SET exclusive_locked_by=? WHERE vm_id=?",
                        (excl["lease_id"], vm_id),
                    )
                self._con.execute("COMMIT")
            except Exception:
                self._con.execute("ROLLBACK")
                raise

            # Phase 2h: VM recém READY pode ter slot para compartilhar com requests da fila.
            to_provision = self._try_fulfill_queued_inside_lock()

        _log.info(
            "vm_ready",
            extra={"extras": {"vm_id": vm_id, "connection_hint": connection_hint}},
        )

        # Provisiona requests da fila que precisam de nova VM (fora do lock).
        for new_vm, pub_key, queued_req in to_provision:
            self._provisioner.provision(
                spec=queued_req.spec,
                vm_id=new_vm.vm_id,
                modules_root=self._tf_modules_root,
                timeout_sec=self._provision_timeout_sec,
                on_ready=lambda hint, vid=new_vm.vm_id: self._on_vm_ready(vid, hint),
                on_failed=lambda err, vid=new_vm.vm_id: self._on_vm_failed(vid, err),
                extra_tf_vars={"ssh_public_key": pub_key},
            )

    def _on_vm_failed(self, vm_id: str, error: str) -> None:
        """Provisão falhou: termina VM + expira leases PENDING + dispara destroy."""
        spec: str | None = None
        to_provision: list[tuple[VMInfo, str, VMRequest]] = []

        with self._lock:
            now_str = _dt_to_str(now_utc())
            # Lê spec antes de terminar a VM (necessário para o destroy)
            vm_row = self._con.execute(
                "SELECT spec FROM vms WHERE vm_id=?", (vm_id,)
            ).fetchone()
            spec = vm_row["spec"] if vm_row else None
            self._con.execute("BEGIN")
            try:
                self._con.execute(
                    "UPDATE vms SET status='TERMINATED' WHERE vm_id=?",
                    (vm_id,),
                )
                self._con.execute(
                    "UPDATE leases SET status='EXPIRED', released_at=? "
                    "WHERE vm_id=? AND status='PENDING'",
                    (now_str, vm_id),
                )
                # Phase 2f: chave SSH deletada — VM falhou, acesso impossível de qualquer forma
                self._con.execute("DELETE FROM vm_keys WHERE vm_id=?", (vm_id,))
                self._con.execute("COMMIT")
            except Exception:
                self._con.execute("ROLLBACK")
                raise

            # Phase 2h: VM falhou → orçamento pode ter liberado → tenta processar fila.
            to_provision = self._try_fulfill_queued_inside_lock()

        _log.error(
            "vm_provision_failed",
            extra={"extras": {"vm_id": vm_id, "error": error[:500]}},
        )
        # Destroy fora do lock: se a provisão foi parcial, terraform destroy
        # é idempotente e removerá os recursos que existirem.
        if spec is not None:
            self._schedule_destroy(vm_id, spec)

        # Provisiona requests da fila fora do lock.
        for new_vm, pub_key, queued_req in to_provision:
            self._provisioner.provision(
                spec=queued_req.spec,
                vm_id=new_vm.vm_id,
                modules_root=self._tf_modules_root,
                timeout_sec=self._provision_timeout_sec,
                on_ready=lambda hint, vid=new_vm.vm_id: self._on_vm_ready(vid, hint),
                on_failed=lambda err, vid=new_vm.vm_id: self._on_vm_failed(vid, err),
                extra_tf_vars={"ssh_public_key": pub_key},
            )

    # ------------------------------------------------------------------ #
    # Destroy                                                              #
    # ------------------------------------------------------------------ #
    def _schedule_destroy(self, vm_id: str, spec: str) -> None:
        """Dispara destruição assíncrona do recurso cloud via provisioner.

        Seguro chamar com ou sem o lock adquirido:
        - TerraformProvisioner.destroy() spawna thread e retorna imediatamente.
        - ImmediateProvisioner.destroy() chama on_done() (apenas log).
        """
        self._provisioner.destroy(
            spec=spec,
            vm_id=vm_id,
            modules_root=self._tf_modules_root,
            timeout_sec=self._provision_timeout_sec,
            on_done=lambda: _log.info(
                "vm_destroy_complete",
                extra={"extras": {"vm_id": vm_id, "spec": spec}},
            ),
            on_failed=lambda err: _log.error(
                "vm_destroy_failed",
                extra={"extras": {
                    "vm_id": vm_id,
                    "spec": spec,
                    "error": err[:500],
                    "action": "manual_destroy_required",
                }},
            ),
        )

    # ------------------------------------------------------------------ #
    # Helpers internos                                                     #
    # ------------------------------------------------------------------ #
    def _check_approval(self, request: VMRequest) -> str | None:
        if request.spec in HUMAN_APPROVAL_REQUIRED_SPECS and not request.human_approved:
            return (
                f"spec {request.spec!r} exige aprovação humana out-of-band. "
                "Setar request.human_approved=True após aprovação registrada."
            )
        if (
            request.spec not in self.policy.spec_whitelist_no_approval
            and not request.human_approved
        ):
            return (
                f"spec {request.spec!r} não está na whitelist sem-aprovação "
                f"({sorted(self.policy.spec_whitelist_no_approval)}). "
                "Marcar human_approved=True após registro."
            )
        return None

    def _find_compatible_vm(self, request: VMRequest) -> VMInfo | None:
        """Encontra VM READY com capacidade (leitura pura, sem PROVISIONING)."""
        if request.exclusive:
            sql = """
                SELECT v.* FROM vms v
                WHERE v.spec = ? AND v.status = 'READY'
                  AND v.exclusive_locked_by IS NULL
                  AND (
                    SELECT COUNT(*) FROM leases l
                    WHERE l.vm_id = v.vm_id AND l.status IN ('PENDING','ACTIVE')
                  ) = 0
                ORDER BY v.created_at LIMIT 1
            """
        else:
            sql = """
                SELECT v.* FROM vms v
                WHERE v.spec = ? AND v.status = 'READY'
                  AND v.exclusive_locked_by IS NULL
                  AND (
                    SELECT COUNT(*) FROM leases l
                    WHERE l.vm_id = v.vm_id AND l.status IN ('PENDING','ACTIVE')
                  ) < 4
                ORDER BY v.created_at LIMIT 1
            """
        row = self._con.execute(sql, (request.spec,)).fetchone()
        return self._row_to_vm(row) if row else None

    def _get_vm_connection_hint(self, vm_id: str) -> str | None:
        row = self._con.execute(
            "SELECT connection_hint FROM vms WHERE vm_id=?", (vm_id,)
        ).fetchone()
        return row["connection_hint"] if row else None

    def _start_provisioning(self, spec: str) -> tuple[VMInfo, str]:
        """Registra VM como PROVISIONING, gera keypair SSH (Phase 2f).

        Returns:
            (VMInfo, public_key_openssh) — chave pública a injetar via terraform.
        """
        from .ssh_key import encrypt_private_key, generate_keypair  # noqa: PLC0415

        vm_id = f"vm-{uuid.uuid4().hex[:10]}"
        now = now_utc()
        private_pem, public_openssh = generate_keypair()
        encrypted = encrypt_private_key(private_pem, self._fernet_key)

        self._con.execute(
            "INSERT INTO vms (vm_id, spec, status, created_at, exclusive_locked_by, connection_hint) "
            "VALUES (?, ?, 'PROVISIONING', ?, NULL, NULL)",
            (vm_id, spec, _dt_to_str(now)),
        )
        self._con.execute(
            "INSERT INTO vm_keys (vm_id, encrypted_private_key, public_key, created_at) "
            "VALUES (?, ?, ?, ?)",
            (vm_id, encrypted, public_openssh, _dt_to_str(now)),
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

    def _create_lease(
        self,
        request: VMRequest,
        vm: VMInfo,
        initial_status: str,
        connection_hint: str | None,
    ) -> VMLease:
        now = now_utc()
        lease_id = f"lease-{uuid.uuid4().hex[:12]}"
        expires_at = lease_expiration(now, request.duration_min)

        self._con.execute("BEGIN")
        try:
            self._con.execute(
                """INSERT INTO leases (
                    lease_id, vm_id, spec, owner, purpose, status, exclusive, priority,
                    created_at, expires_at, released_at, extension_count, connection_hint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)""",
                (
                    lease_id, vm.vm_id, request.spec, request.owner, request.purpose,
                    initial_status,
                    1 if request.exclusive else 0,
                    request.priority,
                    _dt_to_str(now),
                    _dt_to_str(expires_at),
                    connection_hint,
                ),
            )
            if request.exclusive and initial_status == "ACTIVE":
                # Só bloqueia se VM já está READY (share path)
                self._con.execute(
                    "UPDATE vms SET exclusive_locked_by=? WHERE vm_id=?",
                    (lease_id, vm.vm_id),
                )
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise

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

    def _detach_lease_from_vm_tx(
        self,
        lease_id: str,
        vm_id: str,
        is_exclusive: bool,
    ) -> bool:
        """Desvincula lease da VM dentro de uma transação. Retorna True se VM foi terminada."""
        if is_exclusive:
            self._con.execute(
                "UPDATE vms SET exclusive_locked_by=NULL "
                "WHERE vm_id=? AND exclusive_locked_by=?",
                (vm_id, lease_id),
            )
        active_count: int = self._con.execute(
            "SELECT COUNT(*) FROM leases WHERE vm_id=? AND status IN ('PENDING','ACTIVE')",
            (vm_id,),
        ).fetchone()[0]
        if active_count == 0:
            self._con.execute(
                "UPDATE vms SET status='TERMINATED' WHERE vm_id=? AND status != 'TERMINATED'",
                (vm_id,),
            )
            # Phase 2f: remove chave SSH — VM será destruída, acesso não deve ser possível
            self._con.execute("DELETE FROM vm_keys WHERE vm_id=?", (vm_id,))
            return True
        return False

    def _gc_expired(self) -> None:
        now_str = _dt_to_str(now_utc())
        expired = self._con.execute(
            "SELECT lease_id, vm_id, exclusive FROM leases "
            "WHERE status IN ('PENDING','ACTIVE') AND expires_at <= ?",
            (now_str,),
        ).fetchall()
        if not expired:
            return

        orphan_vms: list[sqlite3.Row] = []
        self._con.execute("BEGIN")
        try:
            for row in expired:
                self._con.execute(
                    "UPDATE leases SET status='EXPIRED', released_at=? WHERE lease_id=?",
                    (now_str, row["lease_id"]),
                )
                if row["exclusive"]:
                    self._con.execute(
                        "UPDATE vms SET exclusive_locked_by=NULL "
                        "WHERE vm_id=? AND exclusive_locked_by=?",
                        (row["vm_id"], row["lease_id"]),
                    )
                _log.info("lease_expired_gc", extra={"extras": {"lease_id": row["lease_id"]}})

            # Coleta VMs que ficaram órfãs após expirar os leases (dentro da transação)
            orphan_vms = self._con.execute("""
                SELECT vm_id, spec FROM vms
                WHERE status IN ('PROVISIONING','READY')
                  AND vm_id NOT IN (
                      SELECT DISTINCT vm_id FROM leases
                      WHERE status IN ('PENDING','ACTIVE')
                  )
            """).fetchall()

            if orphan_vms:
                self._con.execute("""
                    UPDATE vms SET status='TERMINATED'
                    WHERE status IN ('PROVISIONING','READY')
                      AND vm_id NOT IN (
                          SELECT DISTINCT vm_id FROM leases
                          WHERE status IN ('PENDING','ACTIVE')
                      )
                """)
                # Phase 2f: remove chaves SSH das VMs órfãs terminadas
                orphan_ids = [r["vm_id"] for r in orphan_vms]
                placeholders = ",".join("?" * len(orphan_ids))
                self._con.execute(
                    f"DELETE FROM vm_keys WHERE vm_id IN ({placeholders})",
                    orphan_ids,
                )
            self._con.execute("COMMIT")
        except Exception:
            self._con.execute("ROLLBACK")
            raise

        # Dispara destroy para VMs órfãs (seguro dentro do lock: TerraformProvisioner
        # spawna thread; ImmediateProvisioner chama on_done síncrono = apenas log)
        for vm_row in orphan_vms:
            self._schedule_destroy(vm_row["vm_id"], vm_row["spec"])

    def _current_cost_per_hour(self) -> float:
        rows = self._con.execute(
            "SELECT spec FROM vms WHERE status IN ('PROVISIONING','READY')"
        ).fetchall()
        return sum(SPEC_COST_USD_PER_HOUR.get(r["spec"], 0.0) for r in rows)

    # ------------------------------------------------------------------ #
    # Phase 2h — fila persistida + preemption                             #
    # ------------------------------------------------------------------ #

    def cancel_queued_request(self, request_id: str, by: str | None = None) -> dict:
        """Cancela um request WAITING na fila.

        Args:
            request_id: ID retornado por request_vm quando outcome=QUEUED.
            by: Identificador de quem cancelou (audit, opcional).

        Returns:
            {"cancelled": True, "request_id": ...}

        Raises:
            AllocatorStoreError: request_id não existe ou não está em status WAITING.
        """
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM queued_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise AllocatorStoreError(
                    f"queued request {request_id!r} não existe"
                )
            if row["status"] != "WAITING":
                raise AllocatorStoreError(
                    f"queued request {request_id!r} não está em status WAITING "
                    f"(status atual: {row['status']!r})"
                )
            self._con.execute(
                "UPDATE queued_requests SET status='CANCELLED' WHERE request_id=?",
                (request_id,),
            )
            _log.info(
                "queued_request_cancelled",
                extra={"extras": {"request_id": request_id, "by": by}},
            )
            return {"cancelled": True, "request_id": request_id}

    def _save_queued_request(self, request: VMRequest) -> str:
        """Persiste request na fila WAITING. Retorna request_id gerado."""
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        self._con.execute(
            """INSERT INTO queued_requests
               (request_id, spec, duration_min, owner, purpose, exclusive, priority,
                human_approved, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'WAITING')""",
            (
                request_id,
                request.spec,
                request.duration_min,
                request.owner,
                request.purpose,
                1 if request.exclusive else 0,
                request.priority,
                1 if request.human_approved else 0,
                _dt_to_str(now_utc()),
            ),
        )
        return request_id

    def _find_preemptable_vms_inside_lock(
        self, spec_cost: float
    ) -> list[sqlite3.Row]:
        """Encontra conjunto mínimo de VMs READY com apenas leases low-priority
        para liberar orçamento suficiente para provisionar spec_cost.

        Seleção greedy: VMs mais caras primeiro até cobrir o déficit.
        Retorna lista vazia se não é possível liberar orçamento suficiente.
        """
        current_cost = self._current_cost_per_hour()
        deficit = (current_cost + spec_cost) - self.policy.max_cost_usd_per_hour
        if deficit <= 0:
            return []

        # VMs READY onde TODOS os leases ativos são de prioridade 'low'.
        candidates = self._con.execute(
            """
            SELECT v.vm_id, v.spec FROM vms v
            WHERE v.status = 'READY'
              AND (
                SELECT COUNT(*) FROM leases l
                WHERE l.vm_id = v.vm_id AND l.status IN ('PENDING','ACTIVE')
              ) > 0
              AND NOT EXISTS (
                SELECT 1 FROM leases l
                WHERE l.vm_id = v.vm_id
                  AND l.status IN ('PENDING','ACTIVE')
                  AND l.priority != 'low'
              )
            """
        ).fetchall()

        if not candidates:
            return []

        # Greedy: preempta VMs mais caras primeiro para minimizar impacto.
        candidates_sorted = sorted(
            candidates,
            key=lambda r: SPEC_COST_USD_PER_HOUR.get(r["spec"], 0.0),
            reverse=True,
        )

        selected: list[sqlite3.Row] = []
        freed = 0.0
        for vm in candidates_sorted:
            selected.append(vm)
            freed += SPEC_COST_USD_PER_HOUR.get(vm["spec"], 0.0)
            if freed >= deficit:
                break

        # Verifica se conseguimos liberar orçamento suficiente.
        return selected if freed >= deficit else []

    def _preempt_vms_inside_lock(
        self, vms: list[sqlite3.Row], reason: str
    ) -> None:
        """Força RELEASED em todos os leases + TERMINATED nas VMs.
        Deve ser chamado DENTRO de uma transação (BEGIN...COMMIT pelo chamador).
        SSH keys são deletadas — acesso às VMs será impossível.
        """
        now_str = _dt_to_str(now_utc())
        for vm in vms:
            vm_id = vm["vm_id"]
            self._con.execute(
                "UPDATE leases SET status='RELEASED', released_at=? "
                "WHERE vm_id=? AND status IN ('PENDING','ACTIVE')",
                (now_str, vm_id),
            )
            self._con.execute(
                "UPDATE vms SET exclusive_locked_by=NULL, status='TERMINATED' WHERE vm_id=?",
                (vm_id,),
            )
            self._con.execute("DELETE FROM vm_keys WHERE vm_id=?", (vm_id,))
            _log.warning(
                "vm_preempted",
                extra={"extras": {"vm_id": vm_id, "spec": vm["spec"], "reason": reason}},
            )

    def _try_fulfill_queued_inside_lock(
        self,
    ) -> list[tuple[VMInfo, str, VMRequest]]:
        """Processa requests WAITING da fila que possam ser atendidos agora.

        Deve ser chamado DENTRO do lock. Retorna lista de (VMInfo, public_key, VMRequest)
        para provisionar FORA do lock. Requests que podem ser atendidos via share de VM
        existente são FULFILLED diretamente (sem provisão nova).

        Ordena por prioridade (high → medium → low) e depois por created_at ASC
        para FIFO dentro de mesma prioridade.
        """
        rows = self._con.execute(
            """SELECT * FROM queued_requests WHERE status='WAITING'
               ORDER BY
                 CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 created_at ASC"""
        ).fetchall()

        to_provision: list[tuple[VMInfo, str, VMRequest]] = []

        for row in rows:
            # Check owner concurrent lease cap
            active_for_owner: int = self._con.execute(
                "SELECT COUNT(*) FROM leases WHERE owner=? AND status IN ('PENDING','ACTIVE')",
                (row["owner"],),
            ).fetchone()[0]
            if active_for_owner >= self.policy.max_active_leases_per_owner:
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
            host_vm = self._find_compatible_vm(request)
            if host_vm is not None:
                self._con.execute(
                    "UPDATE queued_requests SET status='FULFILLED' WHERE request_id=?",
                    (row["request_id"],),
                )
                self._create_lease(
                    request, host_vm,
                    initial_status="ACTIVE",
                    connection_hint=self._get_vm_connection_hint(host_vm.vm_id),
                )
                _log.info(
                    "queued_request_fulfilled_shared",
                    extra={"extras": {
                        "request_id": row["request_id"],
                        "vm_id": host_vm.vm_id,
                        "owner": row["owner"],
                    }},
                )
                continue

            # 2. Precisa de nova VM — verifica cost cap.
            spec_cost = SPEC_COST_USD_PER_HOUR.get(row["spec"], 0.0)
            if self._current_cost_per_hour() + spec_cost > self.policy.max_cost_usd_per_hour:
                continue  # ainda não cabe no orçamento

            # 3. Provisiona nova VM.
            self._con.execute(
                "UPDATE queued_requests SET status='FULFILLED' WHERE request_id=?",
                (row["request_id"],),
            )
            new_vm, public_key = self._start_provisioning(request.spec)
            self._create_lease(request, new_vm, initial_status="PENDING", connection_hint=None)
            to_provision.append((new_vm, public_key, request))
            _log.info(
                "queued_request_fulfilling_provision",
                extra={"extras": {
                    "request_id": row["request_id"],
                    "vm_id": new_vm.vm_id,
                    "owner": row["owner"],
                    "spec": row["spec"],
                }},
            )

        return to_provision
