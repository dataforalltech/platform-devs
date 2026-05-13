"""Ferramentas de configuracao de workspace — paths locais e preferencias globais.

Namespace no ConfigStore: ``workspace``

Chaves canonicas
----------------
REPOS_ROOT      Pasta raiz onde os repositorios/servicos ficam clonados localmente.
                Ex: /home/user/repos  |  C:/Users/user/repositorios
PYTHON_BIN      Interpretador Python padrao (ex: python3, /usr/bin/python3.12).
EDITOR          Editor padrao para o agente abrir arquivos.
DEFAULT_ENV     Perfil de ambiente padrao (local-dev, cloud-dev, ...).

Qualquer chave adicional pode ser armazenada livremente no mesmo namespace.

Tools
-----
- get_workspace_config  : le uma ou todas as chaves do namespace workspace
- set_workspace_config  : define/atualiza uma chave
- list_workspace_config : lista todas as chaves com seus valores
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..knowledge.store import ConfigStore

_log = logging.getLogger(__name__)

WORKSPACE_NS = "workspace"

# Chaves canonicas com descricao e validacao basica
_CANONICAL_KEYS: dict[str, dict] = {
    "REPOS_ROOT": {
        "description": "Pasta raiz dos repositorios/servicos clonados localmente.",
        "validate": lambda v: _validate_path(v),
    },
    "PYTHON_BIN": {
        "description": "Interpretador Python padrao.",
        "validate": None,
    },
    "EDITOR": {
        "description": "Editor padrao (ex: code, vim, nano).",
        "validate": None,
    },
    "DEFAULT_ENV": {
        "description": "Perfil de ambiente padrao (ex: local-dev, cloud-dev).",
        "validate": None,
    },
}


def _validate_path(value: str) -> str | None:
    """Retorna mensagem de erro se o caminho nao existir, None se ok."""
    p = Path(value).expanduser()
    if not p.exists():
        return f"Caminho nao existe: {p}. Crie o diretorio primeiro ou use set_workspace_config com create_dir=true."
    if not p.is_dir():
        return f"Caminho existe mas nao e um diretorio: {p}"
    return None


def get_workspace_config(
    store: ConfigStore,
    *,
    key: str | None = None,
) -> dict[str, Any]:
    """Le configuracao do workspace.

    Se key for passado, retorna apenas aquela chave.
    Se omitido, retorna todas as chaves do namespace workspace
    mais os valores padrao detectados do ambiente.
    """
    if key:
        value = store.get(WORKSPACE_NS, key.upper())
        # Fallback: variavel de ambiente WORKSPACE_<KEY>
        if value is None:
            value = os.environ.get(f"WORKSPACE_{key.upper()}")
        # Fallback especial para REPOS_ROOT
        if value is None and key.upper() == "REPOS_ROOT":
            value = os.environ.get("DEPLOY_REPOS_ROOT") or os.environ.get("REPOS_ROOT")
        return {
            "key": key.upper(),
            "value": value,
            "found": value is not None,
            "source": "store" if store.get(WORKSPACE_NS, key.upper()) is not None else "env_fallback",
        }

    # Todas as chaves
    stored = store.get_namespace(WORKSPACE_NS)

    # Detecta REPOS_ROOT do ambiente se nao estiver no store
    env_repos_root = (
        os.environ.get("DEPLOY_REPOS_ROOT")
        or os.environ.get("REPOS_ROOT")
        or os.environ.get("WORKSPACE_REPOS_ROOT")
    )

    result: dict[str, Any] = {}
    for k, v in stored.items():
        result[k] = {"value": v, "source": "store"}

    if "REPOS_ROOT" not in result and env_repos_root:
        result["REPOS_ROOT"] = {"value": env_repos_root, "source": "env"}

    return {
        "namespace": WORKSPACE_NS,
        "config": result,
        "total": len(result),
        "canonical_keys": list(_CANONICAL_KEYS.keys()),
    }


def set_workspace_config(
    store: ConfigStore,
    *,
    key: str,
    value: str,
    create_dir: bool = False,
) -> dict[str, Any]:
    """Define ou atualiza uma chave no namespace workspace.

    Para REPOS_ROOT: valida que o caminho existe.
    create_dir=True cria o diretorio automaticamente se nao existir.
    """
    key_upper = key.upper()

    canonical = _CANONICAL_KEYS.get(key_upper)

    # Validacao especifica por chave
    if canonical and canonical["validate"]:
        p = Path(value).expanduser()
        if not p.exists():
            if create_dir:
                try:
                    p.mkdir(parents=True, exist_ok=True)
                    _log.info("workspace_dir_created path=%s", p)
                except OSError as exc:
                    return {"error": f"Nao foi possivel criar o diretorio: {exc}", "key": key_upper}
            else:
                err = canonical["validate"](value)
                if err:
                    return {
                        "error": err,
                        "key": key_upper,
                        "tip": "Use create_dir=true para criar o diretorio automaticamente.",
                    }

    store.set(WORKSPACE_NS, key_upper, value)

    # Resolve caminho expandido para retorno
    resolved = str(Path(value).expanduser().resolve()) if key_upper == "REPOS_ROOT" else value

    return {
        "key": key_upper,
        "value": value,
        "resolved": resolved,
        "namespace": WORKSPACE_NS,
        "description": canonical["description"] if canonical else None,
        "action": "set",
    }


def list_workspace_config(
    store: ConfigStore,
) -> dict[str, Any]:
    """Lista todas as chaves do namespace workspace com valores e descricoes canonicas.

    Tambem mostra chaves canonicas ausentes para facilitar o setup inicial.
    """
    stored = store.get_namespace(WORKSPACE_NS)

    env_fallbacks = {
        "REPOS_ROOT": (
            os.environ.get("DEPLOY_REPOS_ROOT")
            or os.environ.get("REPOS_ROOT")
            or os.environ.get("WORKSPACE_REPOS_ROOT")
        ),
    }

    rows: list[dict] = []

    # Chaves canonicas primeiro
    for k, meta in _CANONICAL_KEYS.items():
        stored_val = stored.get(k)
        env_val = env_fallbacks.get(k)
        effective = stored_val or env_val
        rows.append({
            "key": k,
            "value": effective,
            "source": "store" if stored_val else ("env" if env_val else None),
            "set": effective is not None,
            "canonical": True,
            "description": meta["description"],
        })

    # Chaves extras nao canonicas
    for k, v in stored.items():
        if k not in _CANONICAL_KEYS:
            rows.append({
                "key": k,
                "value": v,
                "source": "store",
                "set": True,
                "canonical": False,
                "description": None,
            })

    missing = [r["key"] for r in rows if not r["set"] and r["canonical"]]

    return {
        "namespace": WORKSPACE_NS,
        "config": rows,
        "total": len(rows),
        "missing_canonical": missing,
        "setup_tip": (
            f"Configure as chaves ausentes com set_workspace_config. "
            f"Minimo recomendado: REPOS_ROOT."
        ) if missing else None,
    }
