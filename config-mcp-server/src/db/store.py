"""ConfigStore do config-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do backend de arquivo JSON+Fernet para o **Repository** de alto nível,
ligado ao pool **do tenant** (resolvido credencial-zero via `for_tenant`/
`get_pool_for_tenant`, ORM-H-12). Roda dual-db: o mesmo código serve MySQL
(banco-por-tenant) e PostgreSQL (schema-por-tenant) — o dialeto do pool decide o SQL.

Decisão de arquitetura (migração multi-tenant):
  O store legado era **um arquivo process-global** com namespaces globais
  (``credentials.*``/``env.*``/``workspace``) + por-tenant (``tenants.<id>``).
  No mundo dual-db credencial-zero, TODOS os namespaces passam a viver na tabela
  ``config_entries`` **do tenant que chama** (isolamento por banco). O prefixo
  ``tenants.<id>`` é mantido por back-compat do contrato das tools, mas agora está
  aninhado no próprio banco do tenant (o DB É o tenant). O tenant vem SEMPRE dos
  claims do inner token (INV-3) — nunca de argumento do cliente.

Encriptação at-rest preservada (defense-in-depth): o ``value_encrypted`` guarda a
CIFRA Fernet; o ``Encryptor`` continua na app (DBAs/admin não leem segredos). A
encriptação é ortogonal ao banco — não é delegada ao DB.

Sem SQL manual: cada read/write cai no Repository (`find`/`upsert`/`delete_where`).
As operações que "não encaixam" no CRUD trivial resolvem canonicamente:
  * set por chave natural (namespace, config_key) -> `upsert(conflict_columns=[...])`
    (ON DUPLICATE KEY no MySQL / ON CONFLICT no PG);
  * list_keys/list_namespaces (agregações) -> `find().rows()` + agregação em Python
    (dado minúsculo; evita GROUP BY e mantém orm-lint --strict limpo);
  * delete / delete_namespace -> `delete_where` (soft-delete `excluded=1`).

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`).
"""

from __future__ import annotations

from typing import Any

from ..knowledge.encryptor import EncryptionError, Encryptor
from ..models import ConfigEntryRow
from .schema import CONFIG_ENTRIES_TABLE

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
_SYSTEM_USER = 0

# Sentinela devolvida quando um valor não pode ser decriptado (chave errada/corrompido).
_DECRYPT_ERROR = "<decrypt_error>"


class ConfigStore:
    """Store tenant-scoped: um repositório de config_entries ligado ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e um
    ``Encryptor`` (Fernet, chave global do store em repouso). O repositório é
    ``require_tenant=True`` (fail-closed ORM-H-02), credencial-zero (a sessão nunca
    expõe senha/host).
    """

    def __init__(self, session: Any, encryptor: Encryptor) -> None:
        self._repo = session.repository(ConfigEntryRow, table_name=CONFIG_ENTRIES_TABLE)
        self._enc = encryptor

    # ── helpers ───────────────────────────────────────────────────────────── #

    async def _row(self, namespace: str, key: str) -> dict[str, Any] | None:
        res = await self._repo.find(where={"namespace": namespace, "config_key": key}, limit=1)
        rows = res.rows()
        return rows[0] if rows else None

    def _decrypt(self, token: Any) -> str:
        if token is None:
            return ""
        try:
            return self._enc.decrypt(token)
        except EncryptionError:
            return _DECRYPT_ERROR

    # ── CRUD ──────────────────────────────────────────────────────────────── #

    async def get(self, namespace: str, key: str) -> str | None:
        """Retorna o valor decriptado ou None se não existir."""
        row = await self._row(namespace, key)
        if row is None:
            return None
        token = row.get("value_encrypted")
        if token is None:
            return None
        # get() propaga falha de decriptação (contrato legado: StoreError → erro da tool),
        # ao contrário do get_namespace que degrada para o sentinela.
        return self._enc.decrypt(token)

    async def set(self, namespace: str, key: str, value: str) -> None:
        """Armazena (cria ou atualiza) um valor encriptado por chave natural."""
        await self._repo.upsert(
            {
                "namespace": namespace,
                "config_key": key,
                "value_encrypted": self._enc.encrypt(value),
            },
            conflict_columns=["namespace", "config_key"],
            user_id=_SYSTEM_USER,
        )

    async def delete(self, namespace: str, key: str) -> bool:
        """Remove (soft-delete) uma chave. Retorna True se existia uma linha viva."""
        res = await self._repo.delete_where({"namespace": namespace, "config_key": key}, user_id=_SYSTEM_USER)
        return res.rowcount > 0

    async def delete_namespace(self, namespace: str) -> bool:
        """Remove (soft-delete) um namespace inteiro. Retorna True se havia linhas vivas."""
        res = await self._repo.delete_where({"namespace": namespace}, user_id=_SYSTEM_USER)
        return res.rowcount > 0

    # ── Leitura em lote ───────────────────────────────────────────────────── #

    async def get_namespace(self, namespace: str) -> dict[str, str]:
        """Retorna todos os pares key→value decriptados de um namespace.

        Degrada para ``<decrypt_error>`` em falha de decriptação (não derruba a leitura
        em lote), preservando a semântica do store legado.
        """
        res = await self._repo.find(where={"namespace": namespace})
        result: dict[str, str] = {}
        for row in res.rows():
            result[row["config_key"]] = self._decrypt(row.get("value_encrypted"))
        return result

    async def list_keys(self, namespace: str | None = None) -> dict[str, list[str]]:
        """Lista chaves (nunca valores). namespace=None → todos os namespaces."""
        if namespace:
            res = await self._repo.find(where={"namespace": namespace})
            return {namespace: sorted(row["config_key"] for row in res.rows())}
        res = await self._repo.find()
        grouped: dict[str, list[str]] = {}
        for row in res.rows():
            grouped.setdefault(row["namespace"], []).append(row["config_key"])
        return {ns: sorted(keys) for ns, keys in sorted(grouped.items())}

    async def list_namespaces(self) -> list[str]:
        res = await self._repo.find()
        return sorted({row["namespace"] for row in res.rows()})

    async def namespace_exists(self, namespace: str) -> bool:
        return await self._repo.exists({"namespace": namespace})


__all__ = ["ConfigStore"]
