"""Ferramentas de gestão de variáveis de ambiente por perfil.

Namespaces: env.dev, env.staging, env.production
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..knowledge.store import ConfigStore

logger = logging.getLogger(__name__)

# Secret key patterns — names that indicate sensitive values
_SECRET_NAME_RE = re.compile(
    r"(_TOKEN|_KEY|_SECRET|_PASSWORD|_PASSWD|_CERT)$|PRIVATE|API_KEY",
    re.IGNORECASE,
)

# Safe value patterns — values that are already references or placeholders
_SAFE_VALUE_RE = re.compile(
    r"^\$\{[^}]+\}$"          # ${VAR}
    r"|^/run/secrets/"         # /run/secrets/…
    r"|^dev-"                  # dev-…
    r"|^placeholder$"
    r"|^changeme$"
    r"|^replace.?me$"
    r"|^<.*>$"                 # <something>
    r"|^x+$",                  # xxx, xxxx …
    re.IGNORECASE,
)

_CANONICAL_PROFILES = {
    "local-dev", "local-hml", "cloud-dev", "cloud-hml",
    "cloud-prod", "defaults", "example", "lab", "test",
}


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_NAME_RE.search(key))


def _is_hardcoded_secret(key: str, value: str) -> bool:
    """Return True when the var looks like a secret with a real hardcoded value."""
    if not _is_secret_key(key):
        return False
    if not value:
        return False
    if _SAFE_VALUE_RE.match(value):
        return False
    return True


def _parse_env_lines(text: str) -> list[tuple[str, str | None, str]]:
    """Parse .env text into (key, value, raw_line) triples.

    value is None for blank lines and comments (raw_line is preserved as-is).
    """
    result: list[tuple[str, str | None, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            result.append(("", None, raw))
        elif "=" in stripped:
            k, _, v = stripped.partition("=")
            result.append((k.strip(), v, raw))
        else:
            result.append(("", None, raw))
    return result


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


# ---------------------------------------------------------------------------
# New disk-level helpers
# ---------------------------------------------------------------------------


def read_env_file(
    store: ConfigStore,
    *,
    path: str,
    key_filter: str | None = None,
) -> dict[str, Any]:
    """Read a .env file from disk and return its key-value pairs.

    Args:
        path: Absolute or relative path to the .env file.
        key_filter: Optional substring filter applied to key names (case-insensitive).
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": "FileNotFound", "path": str(p)}

    variables: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            k = k.strip()
            if key_filter is None or key_filter.upper() in k.upper():
                variables[k] = v

    return {"path": str(p), "variables": variables, "count": len(variables)}


def audit_env_files(
    store: ConfigStore,
    *,
    directory: str,
    include_pattern: str = ".env*",
    check_store: bool = True,
) -> dict[str, Any]:
    """Scan .env files in a directory and report issues.

    Args:
        directory: Directory to scan.
        include_pattern: Glob pattern for files to include. Default: '.env*'.
        check_store: If True, check whether secret vars are covered by ConfigStore.
    """
    base = Path(directory).expanduser().resolve()
    files_info: list[dict[str, Any]] = []
    hardcoded_secrets: list[dict[str, Any]] = []
    non_canonical: list[str] = []

    for env_file in sorted(base.glob(include_pattern)):
        if not env_file.is_file():
            continue

        # Derive profile name: everything after the first dot (e.g. .env.local-dev -> local-dev)
        name = env_file.name
        parts = name.split(".", 2)
        profile = parts[2] if len(parts) >= 3 else (parts[1] if len(parts) == 2 else name)

        if profile not in _CANONICAL_PROFILES:
            non_canonical.append(env_file.name)

        variables: dict[str, str] = {}
        try:
            text = env_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", env_file, exc)
            continue

        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, _, v = stripped.partition("=")
                variables[k.strip()] = v

        has_secrets = False
        for k, v in variables.items():
            if _is_hardcoded_secret(k, v):
                has_secrets = True
                in_store = False
                if check_store:
                    try:
                        existing = store.get(f"env.{profile}", k)
                        in_store = existing is not None
                    except Exception:
                        pass
                hardcoded_secrets.append({
                    "file": env_file.name,
                    "key": k,
                    "value_preview": v[:4] + "***" if len(v) > 4 else "***",
                    "in_store": in_store,
                    "suggested_ref": f"${{{k}}}",
                })

        files_info.append({
            "file": env_file.name,
            "profile": profile,
            "var_count": len(variables),
            "has_hardcoded_secrets": has_secrets,
        })

    action_required: list[str] = []
    if hardcoded_secrets:
        action_required.append(
            f"{len(hardcoded_secrets)} hardcoded secret(s) found — run redact_env_secrets"
        )
    if non_canonical:
        action_required.append(
            f"{len(non_canonical)} non-canonical file name(s): {', '.join(non_canonical)}"
        )

    return {
        "directory": str(base),
        "files": files_info,
        "hardcoded_secrets": hardcoded_secrets,
        "hardcoded_secrets_count": len(hardcoded_secrets),
        "non_canonical_files": non_canonical,
        "summary": {"ok": not action_required, "action_required": action_required},
    }


def redact_env_secrets(
    store: ConfigStore,
    *,
    paths: list[str],
    keys: list[str] | None = None,
    auto_detect: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Replace hardcoded secret values in .env files with ${VAR_NAME} references.

    Args:
        paths: List of .env file paths to process.
        keys: Explicit list of key names to redact (in addition to auto-detected ones).
        auto_detect: If True, auto-detect secret keys by name pattern.
        dry_run: If True, report changes without writing files.
    """
    explicit_keys: set[str] = set(keys or [])
    files_modified: list[str] = []
    all_changes: list[dict[str, Any]] = []
    errors: list[str] = []
    files_processed = 0

    for raw_path in paths:
        p = Path(raw_path).expanduser().resolve()
        if not p.exists():
            errors.append(f"FileNotFound: {p}")
            continue

        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"ReadError: {p}: {exc}")
            continue

        files_processed += 1
        parsed = _parse_env_lines(text)
        new_lines: list[str] = []
        file_changes: list[dict[str, Any]] = []

        for key, value, raw in parsed:
            if value is None:
                # blank or comment — preserve as-is
                new_lines.append(raw)
                continue

            should_redact = (key in explicit_keys) or (
                auto_detect and _is_hardcoded_secret(key, value)
            )

            if should_redact:
                new_value = f"${{{key}}}"
                file_changes.append({
                    "file": str(p),
                    "key": key,
                    "old_value_preview": value[:4] + "***" if len(value) > 4 else "***",
                    "new_value": new_value,
                })
                new_lines.append(f"{key}={new_value}")
            else:
                new_lines.append(raw)

        if file_changes:
            all_changes.extend(file_changes)
            files_modified.append(str(p))
            if not dry_run:
                try:
                    p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                except OSError as exc:
                    errors.append(f"WriteError: {p}: {exc}")

    return {
        "dry_run": dry_run,
        "files_processed": files_processed,
        "files_modified": files_modified,
        "total_changes": len(all_changes),
        "changes": all_changes,
        "errors": errors,
    }


def push_env_to_store(
    store: ConfigStore,
    *,
    path: str,
    environment: str,
    overwrite: bool = False,
    secrets_only: bool = False,
) -> dict[str, Any]:
    """Read a .env file from disk and push its vars into ConfigStore.

    Args:
        path: Path to the .env file.
        environment: Target environment name (namespace = env.<environment>).
        overwrite: If False (default), skip vars already in the store.
        secrets_only: If True, only push vars whose names match secret patterns.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": "FileNotFound", "path": str(p)}

    namespace = f"env.{environment}"
    variables: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            variables[k.strip()] = v

    pushed_keys: list[str] = []
    skipped_keys: list[str] = []

    for key, value in variables.items():
        if secrets_only and not _is_secret_key(key):
            skipped_keys.append(key)
            continue

        if not overwrite:
            try:
                existing = store.get(namespace, key)
                if existing is not None:
                    skipped_keys.append(key)
                    continue
            except Exception:
                pass

        try:
            store.set(namespace, key, value)
            pushed_keys.append(key)
        except Exception as exc:
            logger.warning("Failed to push %s to %s: %s", key, namespace, exc)
            skipped_keys.append(key)

    return {
        "environment": environment,
        "namespace": namespace,
        "pushed": len(pushed_keys),
        "skipped": len(skipped_keys),
        "vars": pushed_keys,
    }
