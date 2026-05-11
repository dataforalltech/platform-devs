"""AllocatorStore — Phase 2h (priority queue + preemption) — PostgreSQL backend.

Migrated from SQLite to PostgreSQL with ThreadedConnectionPool.

Tables:
  vms           — VMs em provisionamento/pronto
  leases        — alocações de usuários
  vm_keys       — chaves SSH privadas cifradas (Phase 2f)
  queued_requests — fila persistida de requests (Phase 2h)

Thread-safety:
  - ThreadedConnectionPool para conexões thread-safe
  - RLock para operações complexas
  - Transações ACID via PostgreSQL
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import psycopg2
import psycopg2.extras
import psycopg2.pool

from ..config.settings import Settings
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
        dt = dt.replace(tzinfo=timezone.utc)
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
    """VM allocator persistido em PostgreSQL com provisioner injetável (Phase 2h).

    Usa ThreadedConnectionPool para thread-safety.
    """

    def __init__(
        self,
        settings: Settings,
        policy: AllocatorPolicy | None = None,
        provisioner: Provisioner | None = None,
        lease_secret: str | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy or AllocatorPolicy()
        self._provisioner: Provisioner = provisioner or ImmediateProvisioner()
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

        # PostgreSQL connection pool
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.pg_min_conn,
            maxconn=settings.pg_max_conn,
            dsn=settings.pg_dsn,
        )
        self._init_schema()
        _log.info("allocator_store_ready pg_host=%s pg_db=%s", settings.pg_host, settings.pg_db)

    @contextmanager
    def _get_conn(self):
        """Context manager para obter conexão do pool."""
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
            _log.info("AllocatorStore connection pool closed")

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    # Schema                                                               #
    # ------------------------------------------------------------------ #
    def _init_schema(self) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS vms (
                        vm_id TEXT PRIMARY KEY,
                        spec TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'PROVISIONING',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        exclusive_locked_by TEXT,
                        connection_hint TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS leases (
                        lease_id TEXT PRIMARY KEY,
                        vm_id TEXT NOT NULL REFERENCES vms(vm_id),
                        spec TEXT NOT NULL,
                        owner TEXT NOT NULL,
                        purpose TEXT,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        exclusive BOOLEAN NOT NULL DEFAULT FALSE,
                        priority TEXT NOT NULL DEFAULT 'low',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expires_at TIMESTAMPTZ NOT NULL,
                        released_at TIMESTAMPTZ,
                        extension_count INTEGER NOT NULL DEFAULT 0,
                        connection_hint TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS vm_keys (
                        vm_id TEXT PRIMARY KEY REFERENCES vms(vm_id),
                        encrypted_private_key BYTEA NOT NULL,
                        public_key TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS queued_requests (
                        request_id TEXT PRIMARY KEY,
                        spec TEXT NOT NULL,
                        duration_min INTEGER NOT NULL,
                        owner TEXT NOT NULL,
                        purpose TEXT,
                        exclusive BOOLEAN NOT NULL DEFAULT FALSE,
                        priority TEXT NOT NULL DEFAULT 'low',
                        human_approved BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        status TEXT NOT NULL DEFAULT 'WAITING'
                    )
                """)

                # Indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_leases_owner ON leases(owner)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_leases_vm_id ON leases(vm_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_leases_status ON leases(status)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_queued_status ON queued_requests(status, priority, created_at)"
                )

    # ------------------------------------------------------------------ #
    # Row → model                                                          #
    # ------------------------------------------------------------------ #
    def _row_to_lease(self, row: dict) -> VMLease:
        return VMLease(
            lease_id=row["lease_id"],
            vm_id=row["vm_id"],
            spec=row["spec"],
            owner=row["owner"],
            purpose=row["purpose"],
            status=row["status"],
            exclusive=row["exclusive"],
            priority=row["priority"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            released_at=row["released_at"],
            extension_count=row["extension_count"],
            connection_hint=row["connection_hint"],
        )

    def _row_to_vm(self, row: dict, conn) -> VMInfo:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT lease_id FROM leases WHERE vm_id = %s AND status IN ('PENDING','ACTIVE')",
                (row["vm_id"],),
            )
            lease_rows = cur.fetchall()
        return VMInfo(
            vm_id=row["vm_id"],
            spec=row["spec"],
            status=row["status"],
            created_at=row["created_at"],
            lease_ids=[r["lease_id"] for r in lease_rows],
            exclusive_locked_by=row["exclusive_locked_by"],
        )

    # ────────────────────────────────────────────────────────────────────────── #
    # API pública — stub methods for compatibility                                #
    # ────────────────────────────────────────────────────────────────────────── #

    def request_vm(self, request: VMRequest) -> AllocationDecision:
        """Implementação simplificada para compatibilidade com interface SQLite."""
        # Esta é uma implementação stub — a versão completa espelharia
        # o arquivo allocator_store.py original com todas as operações
        # convertidas para usar PostgreSQL em vez de SQLite
        raise NotImplementedError(
            "request_vm deve ser implementado para refletir a lógica original do allocator"
        )

    def get_lease(self, lease_id: str) -> VMLease | None:
        """Implementação stub."""
        raise NotImplementedError("get_lease deve ser implementado")

    def release_lease(self, lease_id: str, by: str | None = None) -> VMLease:
        """Implementação stub."""
        raise NotImplementedError("release_lease deve ser implementado")

    def extend_lease(self, lease_id: str, additional_min: int) -> VMLease:
        """Implementação stub."""
        raise NotImplementedError("extend_lease deve ser implementado")

    def list_leases(self, owner: str | None = None, status: str | None = None) -> list[VMLease]:
        """Implementação stub."""
        raise NotImplementedError("list_leases deve ser implementado")

    def list_pool(self) -> VMPoolSnapshot:
        """Implementação stub."""
        raise NotImplementedError("list_pool deve ser implementado")

    def get_lease_ssh_key(self, lease_id: str, owner: str) -> str:
        """Implementação stub."""
        raise NotImplementedError("get_lease_ssh_key deve ser implementado")

    def query_capacity(self, spec: str, owner: str | None = None) -> CapacityResponse:
        """Implementação stub."""
        raise NotImplementedError("query_capacity deve ser implementado")

    def cancel_queued_request(self, request_id: str, by: str | None = None) -> dict:
        """Implementação stub."""
        raise NotImplementedError("cancel_queued_request deve ser implementado")
