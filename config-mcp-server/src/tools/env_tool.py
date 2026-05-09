"""Ferramentas de gestão de variáveis de ambiente por perfil.

Namespaces: env.dev, env.staging, env.production
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..knowledge.store import ConfigStore


def get_env_config(
    store: ConfigStore,
    environment: str,
    key_pattern: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Retorna variáveis de um ambiente (valores decriptados).

    Args:
        environment: Perfil de ambiente. Ex: 'dev', 'staging', 'production'.
        key_pattern: Filtro substring no nome das variáveis. Ex: 'DATABASE'.
        limit: Máximo de variáveis retornadas. Padrão: 50.
    """
    ns = f"env.{environment}"
    config = store.get_namespace(ns)
    if key_pattern:
        config = {k: v for k, v in config.items() if key_pattern.upper() in k.upper()}
    if len(config) > limit:
        config = dict(list(config.items())[:limit])
    return {"environment": environment, "config": config, "count": len(config)}


def set_env_var(
    store: ConfigStore,
    environment: str,
    key: str,
    value: str,
) -> dict[str, Any]:
    """Define uma variável de ambiente para um perfil."""
    store.set(f"env.{environment}", key, value)
    return {"success": True, "environment": environment, "key": key}


def list_environments(store: ConfigStore) -> dict[str, Any]:
    """Lista os ambientes configurados e a quantidade de variáveis em cada um."""
    envs: dict[str, int] = {}
    for ns in store.list_namespaces():
        if ns.startswith("env."):
            env_name = ns.removeprefix("env.")
            envs[env_name] = len(store.list_keys(ns).get(ns, []))
    return {"environments": envs, "count": len(envs)}


def sync_env_file(
    store: ConfigStore,
    target_path: str,
    environment: str,
    merge: bool = True,
) -> dict[str, Any]:
    """Escreve (ou mescla) variáveis do store em um arquivo .env.

    Args:
        target_path: Caminho do arquivo .env a criar/atualizar.
        environment: Perfil de ambiente cujas variáveis serão escritas.
        merge: Se True, mantém variáveis existentes não presentes no store.
    """
    ns = f"env.{environment}"
    config = store.get_namespace(ns)

    if not config:
        return {
            "success": False,
            "error": f"Nenhuma variável encontrada para o ambiente '{environment}'.",
        }

    path = Path(target_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, str] = {}
    if merge and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    merged = {**existing, **config}
    lines = [
        f"# Gerado por config-mcp — ambiente: {environment}",
        "",
        *[f"{k}={v}" for k, v in sorted(merged.items())],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "success": True,
        "path": str(path),
        "environment": environment,
        "vars_from_store": len(config),
        "vars_total": len(merged),
    }
