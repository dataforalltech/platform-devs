"""Ferramentas de gestão de credenciais no ConfigStore (async, tenant-scoped).

Namespaces convencionais:
  credentials.acr      → ACR_USERNAME, ACR_PASSWORD, ACR_REGISTRY, ACR_NAMESPACE
  credentials.github   → GITHUB_TOKEN, GITHUB_ORG
  credentials.portainer → PORTAINER_WEBHOOK_<service>
  credentials.internal → INTERNAL_API_TOKEN, etc.
"""

from __future__ import annotations

from typing import Any

from ..db.store import ConfigStore


async def get_credential(store: ConfigStore, namespace: str, key: str) -> dict[str, Any]:
    """Recupera um valor de credencial do store."""
    value = await store.get(namespace, key)
    if value is None:
        return {"found": False, "namespace": namespace, "key": key}
    return {"found": True, "namespace": namespace, "key": key, "value": value}


async def set_credential(
    store: ConfigStore,
    namespace: str,
    key: str,
    value: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Define (cria ou atualiza) uma credencial no store."""
    await store.set(namespace, key, value)
    result: dict[str, Any] = {"success": True, "namespace": namespace, "key": key}
    if description:
        result["description"] = description
    return result


async def list_credentials(store: ConfigStore, namespace: str | None = None) -> dict[str, Any]:
    """Lista namespaces e chaves disponíveis (nunca valores)."""
    keys_map = await store.list_keys(namespace)
    total = sum(len(v) for v in keys_map.values())
    return {"namespaces": keys_map, "total_keys": total}


async def set_credential_secure(store: ConfigStore, namespace: str, key: str) -> dict[str, Any]:
    """Define uma credencial via input seguro no terminal (getpass).

    O valor nunca trafega pelo canal MCP — lido diretamente do TTY do processo config-mcp.
    Tool na denylist do gateway (_EXCLUDE_TOOLS): depende de TTY, só via stdio.
    """
    import getpass
    import sys

    try:
        prompt = f"\n[config-mcp] {namespace}.{key} (sem echo): "
        print(
            f"\n[config-mcp] Aguardando input seguro para '{namespace}.{key}'...",
            file=sys.stderr,
        )
        value = getpass.getpass(prompt=prompt)
        if not value:
            return {
                "success": False,
                "namespace": namespace,
                "key": key,
                "error": "Valor vazio — nenhuma alteração feita.",
            }
        await store.set(namespace, key, value)
        return {"success": True, "namespace": namespace, "key": key}
    except (KeyboardInterrupt, EOFError):
        return {
            "success": False,
            "namespace": namespace,
            "key": key,
            "error": "Operação cancelada (Ctrl+C ou EOF).",
        }


async def delete_credential(store: ConfigStore, namespace: str, key: str) -> dict[str, Any]:
    """Remove uma credencial do store."""
    deleted = await store.delete(namespace, key)
    return {"deleted": deleted, "namespace": namespace, "key": key}
