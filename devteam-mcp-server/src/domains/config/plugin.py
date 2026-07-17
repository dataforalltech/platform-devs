"""Plugin do domínio *config* — contrato ``register()`` do server consolidado.

Espelha o ``plugin`` do domínio *architecture* (ver MCP_DEVTEAM_CONSOLIDATION_DESIGN.md):
expõe um ``register() -> dict`` que o agregador (`src/server/mcp_server.py`) consome. O
agregador NÃO conhece a lógica do domínio — só mescla os ``schemas`` (chaves já
prefixadas ``config_<op>``) e roteia por prefixo.

Duas particularidades deste domínio vs. o architecture (persona *stateful* config-mcp):
  * ``ConfigStore`` exige, além da sessão tenant-scoped, um ``Encryptor`` Fernet
    (encriptação at-rest dos valores — defense-in-depth). O server-fonte o construía no
    boot (fail-fast); aqui, como o agregador não tem hook de boot por-domínio, o
    Encryptor é construído UMA vez (lazy, cache de módulo) a partir da master key
    resolvida via Vault→env (``CONFIG_MCP_MASTER_KEY``) e reusado por-request. Chave
    ausente/inválida falha no PRIMEIRO uso de uma tool store-backed (fail-closed em
    call-time em vez de boot-time).
  * ``status`` e ``get_physical_info`` são **storeless** (não tocam o store nem tenant):
    o dispatcher as roteia sem construir a Store/Encryptor, preservando a semântica do
    fonte (que as tratava como exempt/compute-only).

``register()`` devolve ``{name, schemas, dispatch, ensure_schema}`` (contrato uniforme
do agregador; ``ensure_schema`` vem de ``.db.schema``).
"""

from __future__ import annotations

import os
from typing import Any

from . import catalog
from .catalog import DOMAIN
from .config.secrets import load_secret
from .db.schema import ensure_schema
from .db.store import ConfigStore
from .knowledge.encryptor import Encryptor

# Prefixo de tool do domínio (``config_``). O agregador descobre o domínio por
# longest-prefix-match (``name.startswith(f"{DOMAIN}_")``).
_PREFIX = f"{DOMAIN}_"

# Encryptor Fernet do store (encriptação at-rest). Construído uma vez, lazy, e reusado.
_encryptor: Encryptor | None = None


def _get_encryptor() -> Encryptor:
    """Constrói (uma vez) o Encryptor Fernet a partir da master key do store.

    A chave é resolvida via Vault→env (``CONFIG_MCP_MASTER_KEY``), idêntico ao fonte
    (``settings.resolve_master_key`` = ``load_secret("CONFIG_MCP_MASTER_KEY", env)``). O
    ``Encryptor.__init__`` valida o formato da chave Fernet — chave ausente/inválida
    levanta ``EncryptionError``, propagada como erro da tool (fail-closed em call-time).
    """
    global _encryptor
    if _encryptor is None:
        _encryptor = Encryptor(load_secret("CONFIG_MCP_MASTER_KEY", os.getenv("CONFIG_MCP_MASTER_KEY", "")))
    return _encryptor


async def _dispatch(name: str, args: dict[str, Any], session: Any) -> dict[str, Any]:
    """Retira o prefixo, roteia storeless vs. store-backed e delega ao catálogo.

    O agregador chama ``dispatch(tool_name, args, session)`` com o nome JÁ prefixado
    (``config_get_env_config``) e a sessão tenant-scoped. As tools storeless
    (``status``/``get_physical_info``) não tocam o store — despachadas sem construir a
    Store/Encryptor. As demais recebem um ``ConfigStore`` ligado ao pool do tenant.
    """
    op = name[len(_PREFIX) :] if name.startswith(_PREFIX) else name
    if op in catalog._STORELESS_TOOLS:
        return await catalog.dispatch_storeless(op)
    store = ConfigStore(session, _get_encryptor())
    return await catalog.dispatch(op, args, store)


def register() -> dict[str, Any]:
    """Contrato do plugin consumido pelo agregador (ver docstring do módulo)."""
    schemas = {f"{_PREFIX}{op}": meta for op, meta in catalog._TOOL_SCHEMAS.items()}
    return {
        "name": DOMAIN,
        "schemas": schemas,
        "dispatch": _dispatch,
        "ensure_schema": ensure_schema,
    }
