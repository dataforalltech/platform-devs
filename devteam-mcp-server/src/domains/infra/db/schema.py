"""Bootstrap de schema por-tenant via DDL IR canônico (``platform_database.orm.ddl``).

Nada de ``CREATE TABLE`` escrito à mão: cada tabela é um ``CreateTable`` derivado do
modelo Pydantic (``create_table_from_model``, que injeta as colunas padrão da
plataforma) e ganha a **constraint UNIQUE de chave natural** como constraint de tabela —
renderizada DENTRO do ``CREATE TABLE IF NOT EXISTS``, portanto idempotente (criada só
junto com a tabela, sem ``CREATE INDEX`` separado que quebraria no re-run).

As UNIQUE existem para o app ler/atualizar por chave de negócio (``vm_id``/``lease_id``/
``request_id``) com segurança de unicidade — os IDs de negócio são gerados por ``uuid``,
então nunca colidem, mas a UNIQUE documenta e garante a invariante 1:1 (ex.: ``vm_keys``
↔ ``vms``).

Idempotente e multi-engine: ``emit_ddl(script, engine)`` compila para o dialeto do
tenant (mysql/postgresql), então o MESMO bootstrap serve o dual-db.

NOTA (FKs/índices): as FKs SQLite originais (``leases.vm_id``/``vm_keys.vm_id`` →
``vms(vm_id)``) e os índices secundários (``idx_leases_*``/``idx_queued_status``) NÃO são
reintroduzidos aqui — o pool de VMs é pequeno (cost-capped) e a integridade é mantida
pela lógica do store; recriar índices separados quebraria a idempotência do bootstrap
(``CREATE INDEX`` não é ``IF NOT EXISTS`` no IR). São um follow-up de migração versionada.
"""

from __future__ import annotations

from typing import Any

from platform_database.orm.ddl import (
    CreateTable,
    MigrationScript,
    UniqueConstraintSpec,
    create_table_from_model,
    emit_ddl,
)

from ..models.rows import LeaseRow, QueuedRequestRow, VmKeyRow, VmRow

# Nomes físicos das tabelas (table-case "lower" por padrão — tenants novos).
VMS_TABLE = "vms"
LEASES_TABLE = "leases"
VM_KEYS_TABLE = "vm_keys"
QUEUED_TABLE = "queued_requests"


def _with_unique(model: type, table_name: str, *, unique: list[str], unique_name: str) -> CreateTable:
    """``CreateTable`` do modelo + uma constraint UNIQUE de tabela sobre a chave natural."""
    ct = create_table_from_model(model, table_name=table_name)
    return ct.model_copy(update={"uniques": [UniqueConstraintSpec(name=unique_name, columns=unique)]})


def build_migration() -> MigrationScript:
    """A migração de criação das 4 tabelas do allocator (up-only, idempotente)."""
    return MigrationScript(
        up=[
            _with_unique(VmRow, VMS_TABLE, unique=["vm_id"], unique_name="uq_vms_vm_id"),
            _with_unique(LeaseRow, LEASES_TABLE, unique=["lease_id"], unique_name="uq_leases_lease_id"),
            _with_unique(VmKeyRow, VM_KEYS_TABLE, unique=["vm_id"], unique_name="uq_vm_keys_vm_id"),
            _with_unique(
                QueuedRequestRow,
                QUEUED_TABLE,
                unique=["request_id"],
                unique_name="uq_queued_request_id",
            ),
        ]
    )


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria as 4 tabelas no banco do tenant (idempotente ``IF NOT EXISTS``).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = [
    "VMS_TABLE",
    "LEASES_TABLE",
    "VM_KEYS_TABLE",
    "QUEUED_TABLE",
    "build_migration",
    "ensure_schema",
]
