"""Store do dev-twin-mcp — 100% sobre o ORM canônico (`platform_database.orm`).

Reescrito do psycopg2 cru para o **Repository** de alto nível + Query IR, ligado ao
pool **do tenant** (resolvido credencial-zero via `for_tenant`/`get_pool_for_tenant`,
ORM-H-12). Roda dual-db: o mesmo código serve MySQL (banco-por-tenant) e PostgreSQL
(schema-por-tenant) — o dialeto do pool decide o SQL.

Sem SQL manual: cada read/write cai no Repository (`find`/`insert`/`update_where`/
`delete_where`). A camada é uma tabela de identidade/token com semântica própria:

  * ``register``  -> `insert` (token novo a cada chamada; UNIQUE(token) protege
    colisão de hash; retorna o token PLAINTEXT uma única vez);
  * ``validate``  -> `find` por ``token_prefix`` (só linhas vivas, `excluded=0`) +
    checagem de expiração + `bcrypt.checkpw` (verificação constante);
  * ``revoke``    -> soft-delete canônico (`delete_where` -> `excluded=1`) por
    ``user_id`` (ou por token bruto: prefix + bcrypt, soft-delete por ``id``);
  * ``rotate``    -> lê o token vivo do ``user_id``, revoga (soft-delete) e `register`
    um novo preservando name/email/role/environment/scopes/tenant_id;
  * ``touch``     -> `update_where` de ``last_used_at`` (só linhas vivas);
  * ``list_all``  -> `find` ordenado (nunca expõe ``token``/``token_prefix``;
    `include_revoked` mapeia para `include_soft_deleted`).

Convenções: `PLATFORM_CONVENTIONS` (soft-delete `excluded=0`, auditoria
`id_user_*`/`timestamp_refresh`). Como `id_user_created` é NOT NULL sem default, todo
write carimba o usuário-sistema (`_SYSTEM_USER`); a ``active`` canônica (default 1)
é vestigial — quem carrega a revogação é ``excluded``.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from platform_database.orm import Sort, SortDirection, UniqueViolationError

from ..models import AgentTokenRow
from .schema import AGENT_TOKENS_TABLE

# Usuário-sistema carimbado nas colunas de auditoria (id_user_created/id_user_modify).
_SYSTEM_USER = 0

# Colunas expostas por list_all — NUNCA token nem token_prefix (segredos).
# ``excluded`` (0=ativo, 1=revogado) substitui a antiga semântica de ``active``.
_LIST_COLUMNS = (
    "id",
    "user_id",
    "name",
    "email",
    "role",
    "scopes",
    "environment",
    "tenant_id",
    "excluded",
    "created_at",
    "last_used_at",
    "expires_at",
)


class TokenStoreError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    """Interpreta um timestamp de coluna (str ISO ou datetime) como aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _decode_scopes(value: Any) -> list[str]:
    """Desserializa a coluna scopes (TEXT JSON) numa lista; falha-seguro para []."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return loaded if isinstance(loaded, list) else []
    return []


class TokenStore:
    """Store tenant-scoped: 1 repositório (agent_tokens) ligado ao pool do tenant.

    Recebe uma ``TenantSession`` (de ``platform_database.orm.for_tenant``) e cria o
    repositório canônico por ela — ``require_tenant=True`` (fail-closed ORM-H-02),
    credencial-zero (a sessão nunca expõe senha/host).
    """

    def __init__(self, session: Any) -> None:
        self._tokens = session.repository(AgentTokenRow, table_name=AGENT_TOKENS_TABLE)

    # ── Validação ─────────────────────────────────────────────────────────── #

    async def validate(self, token: str) -> dict[str, Any] | None:
        """Valida o token e retorna o registro vivo do usuário ou None.

        Lookup por ``token_prefix`` (só linhas vivas, `excluded=0`) + checagem de
        expiração + `bcrypt.checkpw`. Retorna None se: token não existe, revogado
        (soft-deletado), expirado, ou bcrypt falha.
        """
        prefix = token[:8]
        now = _now()
        res = await self._tokens.find(where={"token_prefix": prefix})
        for record in res.rows():
            expires = _parse_dt(record.get("expires_at"))
            if expires is not None and now > expires:
                continue
            token_hash = record.get("token") or ""
            try:
                if bcrypt.checkpw(token.encode(), str(token_hash).encode()):
                    return record
            except (ValueError, TypeError):
                continue
        return None

    # ── CRUD ──────────────────────────────────────────────────────────────── #

    async def register(
        self,
        name: str,
        email: str,
        role: str = "developer",
        environment: str = "dev",
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Cria um novo token e retorna o registro completo.

        O token plaintext é retornado **apenas uma vez** — não é armazenado no DB.
        O DB armazena somente o bcrypt hash e o prefix para lookup.
        """
        token = secrets.token_urlsafe(32)
        token_prefix = token[:8]
        token_hash = bcrypt.hashpw(token.encode(), bcrypt.gensalt(rounds=10)).decode()
        user_id = secrets.token_hex(8)
        now = _now()
        expires_at = now + timedelta(days=expires_in_days) if expires_in_days else None
        scopes_list = scopes if scopes else ["*"]

        try:
            await self._tokens.insert(
                {
                    "token": token_hash,
                    "token_prefix": token_prefix,
                    "user_id": user_id,
                    "name": name,
                    "email": email,
                    "role": role,
                    "scopes": json.dumps(scopes_list),
                    "environment": environment,
                    "tenant_id": tenant_id,
                    "created_at": now.isoformat(),
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                user_id=_SYSTEM_USER,
            )
        except UniqueViolationError as exc:
            raise TokenStoreError(f"Erro ao registrar token: {exc}") from exc

        return {
            "token": token,  # plaintext — retornado apenas uma vez
            "user_id": user_id,
            "name": name,
            "email": email,
            "role": role,
            "scopes": scopes_list,
            "environment": environment,
            "tenant_id": tenant_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
        }

    async def revoke(self, identifier: str) -> dict[str, Any]:
        """Revoga por user_id (preferencial) ou por token bruto (soft-delete canônico).

        Revogação = soft-delete (`excluded=1`): as leituras filtram `excluded=0`, então
        o token some. Retorna quantos registros foram afetados.
        """
        res = await self._tokens.delete_where({"user_id": identifier}, user_id=_SYSTEM_USER)
        affected = res.rowcount

        if affected == 0:
            # Tentativa por token bruto: prefix lookup (vivos) + bcrypt.
            prefix = identifier[:8]
            rows = (await self._tokens.find(where={"token_prefix": prefix})).rows()
            for row in rows:
                token_hash = row.get("token") or ""
                try:
                    matched = bcrypt.checkpw(identifier.encode(), str(token_hash).encode())
                except (ValueError, TypeError):
                    continue
                if matched:
                    del_res = await self._tokens.delete_where({"id": row["id"]}, user_id=_SYSTEM_USER)
                    affected = del_res.rowcount
                    break

        return {"revoked": affected > 0, "affected": affected, "identifier": identifier}

    async def rotate(self, identifier: str) -> dict[str, Any]:
        """Revoga o token vivo do user_id e emite um novo para o mesmo usuário.

        Args:
            identifier: user_id do usuário a ter o token rotacionado.
        """
        rows = (await self._tokens.find(where={"user_id": identifier}, limit=1)).rows()
        if not rows:
            raise TokenStoreError(f"user_id '{identifier}' não encontrado ou já revogado.")
        record = rows[0]
        # Revoga (soft-delete) todos os tokens vivos do user_id.
        await self._tokens.delete_where({"user_id": identifier}, user_id=_SYSTEM_USER)

        return await self.register(
            name=record["name"],
            email=record["email"],
            role=record["role"],
            environment=record["environment"],
            scopes=_decode_scopes(record.get("scopes")),
            tenant_id=record.get("tenant_id"),
        )

    async def touch(self, user_id: str) -> None:
        """Atualiza last_used_at para o usuário (só linhas vivas)."""
        await self._tokens.update_where(
            {"user_id": user_id},
            {"last_used_at": _now().isoformat()},
            user_id=_SYSTEM_USER,
        )

    async def list_all(
        self,
        include_revoked: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lista tokens sem expor token plaintext nem token hash.

        Nunca retorna as colunas `token` ou `token_prefix`. ``include_revoked=True``
        mapeia para `include_soft_deleted` (mostra também os revogados, `excluded=1`).
        """
        res = await self._tokens.find(
            order_by=[Sort(column="created_at", direction=SortDirection.DESC)],
            limit=limit,
            offset=offset,
            include_soft_deleted=include_revoked,
        )
        result: list[dict[str, Any]] = []
        for row in res.rows():
            record = {col: row.get(col) for col in _LIST_COLUMNS}
            record["scopes"] = _decode_scopes(record.get("scopes"))
            result.append(record)
        return result
