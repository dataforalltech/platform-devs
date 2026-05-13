"""Ferramentas de gestão de arquivos .env — leitura, escrita e sync com o registry.

Tools
-----
- read_env_file        : lê um arquivo .env e retorna o dict de variáveis
- set_env_var          : define/atualiza uma variável num arquivo .env (preserva comentários)
- sync_service_urls    : detecta vars URL_* no .env e atualiza com as URLs do registry

Convenção de nomes
------------------
`URL_ADMIN` → serviço chamado `platform-admin` ou `admin`
`URL_AUTH`  → `platform-auth` ou `auth`

A busca no registry é feita por:
  1. Nome exato da chave sem prefixo URL_ (case-insensitive) — ex: URL_ADMIN → "admin"
  2. Nome com prefixo "platform-" — ex: "platform-admin"
  3. Mapeamento explícito passado pelo chamador via `url_map`
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..db.store import ServiceStore

_log = logging.getLogger(__name__)


# ── Helpers de parse/serialização ────────────────────────────────────────────

def _parse_env_file(path: Path) -> list[tuple[str, str]]:
    """Lê um .env e retorna lista de (tipo, conteúdo) onde tipo é 'comment', 'blank' ou 'var:KEY'."""
    lines: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            lines.append(("blank", line))
        elif stripped.startswith("#"):
            lines.append(("comment", line))
        elif "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            lines.append((f"var:{key}", line))
        else:
            lines.append(("other", line))
    return lines


def _lines_to_dict(lines: list[tuple[str, str]]) -> dict[str, str]:
    """Extrai apenas as variáveis do resultado de _parse_env_file."""
    result: dict[str, str] = {}
    for kind, raw in lines:
        if kind.startswith("var:"):
            key, _, val = raw.strip().partition("=")
            result[key.strip()] = val.strip()
    return result


def _write_env_lines(path: Path, lines: list[tuple[str, str]]) -> None:
    content = "\n".join(raw for _, raw in lines) + "\n"
    path.write_text(content, encoding="utf-8")


# ── Tools públicas ────────────────────────────────────────────────────────────

def read_env_file(
    _store: ServiceStore,
    *,
    path: str,
    key_filter: str | None = None,
) -> dict[str, Any]:
    """Lê um arquivo .env e retorna as variáveis como dict.

    Args:
        path: Caminho do arquivo .env (absoluto ou relativo ao cwd).
        key_filter: Substring opcional para filtrar chaves (case-insensitive).
    """
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": "FileNotFound", "path": str(p.resolve())}

    lines = _parse_env_file(p)
    variables = _lines_to_dict(lines)

    if key_filter:
        variables = {k: v for k, v in variables.items() if key_filter.upper() in k.upper()}

    return {
        "path": str(p.resolve()),
        "variables": variables,
        "count": len(variables),
    }


def set_env_var(
    _store: ServiceStore,
    *,
    path: str,
    key: str,
    value: str,
    create_if_missing: bool = True,
    comment: str | None = None,
) -> dict[str, Any]:
    """Define ou atualiza uma variável em um arquivo .env.

    Preserva comentários, ordem e formatação existentes.
    Se a variável não existir e create_if_missing=True, adiciona ao final.

    Args:
        path: Caminho do arquivo .env.
        key: Nome da variável (ex: URL_ADMIN).
        value: Novo valor.
        create_if_missing: Adicionar ao final se a chave não existir. Default: True.
        comment: Comentário opcional a adicionar acima da variável (só quando criando).
    """
    p = Path(path).expanduser()

    if not p.exists():
        if not create_if_missing:
            return {"error": "FileNotFound", "path": str(p.resolve())}
        # Cria arquivo novo
        p.parent.mkdir(parents=True, exist_ok=True)
        lines: list[tuple[str, str]] = []
    else:
        lines = _parse_env_file(p)

    key_kind = f"var:{key}"
    old_value: str | None = None
    updated = False

    new_lines: list[tuple[str, str]] = []
    for kind, raw in lines:
        if kind == key_kind:
            old_value = raw.strip().partition("=")[2].strip()
            new_lines.append((key_kind, f"{key}={value}"))
            updated = True
        else:
            new_lines.append((kind, raw))

    if not updated:
        if not create_if_missing:
            return {
                "error": "KeyNotFound",
                "key": key,
                "path": str(p.resolve()),
                "hint": "Use create_if_missing=true para criar a variável",
            }
        # Adiciona ao final
        if new_lines and new_lines[-1][0] != "blank":
            new_lines.append(("blank", ""))
        if comment:
            new_lines.append(("comment", f"# {comment}"))
        new_lines.append((key_kind, f"{key}={value}"))

    _write_env_lines(p, new_lines)
    _log.info("set_env_var path=%s key=%s updated=%s", p, key, updated)

    return {
        "path": str(p.resolve()),
        "key": key,
        "old_value": old_value,
        "new_value": value,
        "action": "updated" if updated else "created",
    }


def sync_service_urls(
    store: ServiceStore,
    *,
    path: str,
    url_map: dict[str, str] | None = None,
    url_suffix: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sincroniza variáveis URL_* de um .env com as URLs registradas no registry.

    Para cada variável `URL_<NAME>` no arquivo .env, tenta encontrar o serviço
    correspondente no registry e atualiza o valor com a URL correta.

    Lógica de resolução do nome do serviço:
      1. Mapeamento explícito via `url_map` (ex: {"URL_ADMIN": "platform-admin"})
      2. Nome derivado da chave: URL_ADMIN → busca "admin" ou "platform-admin"

    Args:
        path: Caminho do arquivo .env a atualizar.
        url_map: Mapeamento explícito {ENV_VAR: service_name}. Ex: {"URL_ADMIN": "platform-admin"}.
        url_suffix: Sufixo a acrescentar na URL. Ex: "/api/v1". Default: "".
        dry_run: Se True, apenas simula sem alterar o arquivo.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": "FileNotFound", "path": str(p.resolve())}

    lines = _parse_env_file(p)
    variables = _lines_to_dict(lines)
    url_map = url_map or {}

    # Pega todos os serviços do registry de uma vez
    all_services = store.list_all()
    svc_by_name: dict[str, dict] = {s["name"].lower(): s for s in all_services}

    def _resolve_service(env_key: str) -> dict | None:
        """Retorna o registro do serviço para um env var URL_<X>."""
        # 1. Mapeamento explícito
        if env_key in url_map:
            target = url_map[env_key].lower()
            return svc_by_name.get(target)

        # 2. Derivação automática: URL_ADMIN → "admin" ou "platform-admin"
        if env_key.startswith("URL_"):
            suffix = env_key[4:].lower()  # "admin"
            return (
                svc_by_name.get(suffix)
                or svc_by_name.get(f"platform-{suffix}")
            )
        return None

    changes: list[dict[str, str]] = []
    not_found: list[str] = []
    skipped: list[str] = []

    for env_key, current_val in variables.items():
        if not (env_key.startswith("URL_") or env_key in url_map):
            continue

        svc = _resolve_service(env_key)
        if svc is None:
            not_found.append(env_key)
            continue

        # Constrói nova URL: preferência por external_url, depois url, depois host:port
        base_url = (
            svc.get("external_url")
            or svc.get("url")
            or (f"http://{svc['host']}:{svc['port']}" if svc.get("host") and svc.get("port") else None)
        )
        if not base_url:
            not_found.append(env_key)
            continue

        new_url = base_url.rstrip("/") + url_suffix

        # Preserva sufixo de path existente se url_suffix não for fornecido
        if not url_suffix and current_val:
            # Tenta extrair o path da URL atual e reaplicar
            existing_path = _extract_url_path(current_val)
            if existing_path and existing_path != "/":
                new_url = base_url.rstrip("/") + existing_path

        if new_url == current_val:
            skipped.append(env_key)
            continue

        changes.append({
            "key": env_key,
            "old": current_val,
            "new": new_url,
            "service": svc["name"],
            "port": str(svc.get("port", "")),
        })

    if not dry_run and changes:
        # Aplica as mudanças no arquivo
        new_lines: list[tuple[str, str]] = []
        for kind, raw in lines:
            if kind.startswith("var:"):
                k = kind[4:]
                change = next((c for c in changes if c["key"] == k), None)
                if change:
                    new_lines.append((kind, f"{k}={change['new']}"))
                    continue
            new_lines.append((kind, raw))
        _write_env_lines(p, new_lines)

    _log.info(
        "sync_service_urls path=%s changes=%d not_found=%d dry_run=%s",
        p, len(changes), len(not_found), dry_run,
    )

    return {
        "path": str(p.resolve()),
        "dry_run": dry_run,
        "changes": changes,
        "skipped_already_correct": skipped,
        "not_found_in_registry": not_found,
        "total_changes": len(changes),
    }


def _extract_url_path(url: str) -> str:
    """Extrai o path de uma URL. Ex: 'http://localhost:8000/api/v1' → '/api/v1'."""
    # Remove scheme://host:port
    match = re.match(r"https?://[^/]+(/.*)$", url)
    if match:
        return match.group(1)
    return ""
