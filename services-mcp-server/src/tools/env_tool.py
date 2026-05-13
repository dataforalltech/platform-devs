"""Ferramentas de gestão de arquivos .env — leitura, escrita, audit e sync.

Tools
-----
- read_env_file        : lê um arquivo .env e retorna o dict de variáveis
- set_env_var          : define/atualiza uma variável num arquivo .env (preserva comentários)
- sync_service_urls    : detecta vars URL_* no .env e atualiza com as URLs do registry
- audit_env_files      : escaneia todos .env.* de um diretório e reporta problemas
- redact_env_secrets   : substitui valores hardcoded de secrets por ${VAR_NAME} references

Convenção de nomes
------------------
`URL_ADMIN` -> serviço chamado `platform-admin` ou `admin`
`URL_AUTH`  -> `platform-auth` ou `auth`

A busca no registry é feita por:
  1. Nome exato da chave sem prefixo URL_ (case-insensitive) — ex: URL_ADMIN -> "admin"
  2. Nome com prefixo "platform-" — ex: "platform-admin"
  3. Mapeamento explícito passado pelo chamador via `url_map`

Padrão de secrets
-----------------
Vars consideradas secrets: chaves contendo SECRET, PASSWORD, TOKEN, KEY, DSN, CERT, PRIVATE.
Valores safe: vazio, `${VAR}`, `*` (placeholder), valores começando com `/run/secrets/`.
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
    """Extrai o path de uma URL. Ex: 'http://localhost:8000/api/v1' -> '/api/v1'."""
    match = re.match(r"https?://[^/]+(/.*)$", url)
    if match:
        return match.group(1)
    return ""


# ── Padrões de secrets ────────────────────────────────────────────────────────

# Regex que identifica se uma variável é um secret pelo nome.
# Regras:
#   - Sufixos exactos: _TOKEN, _KEY, _SECRET, _PASSWORD, _PASSWD, _DSN, _CERT, _CREDENTIAL
#   - TOKEN/KEY só batem quando no FINAL do nome (ex: INTERNAL_API_TOKEN sim, TOKEN_EXPIRE nao)
#   - PRIVATE em qualquer posição: PRIVATE_KEY, RSA_PRIVATE
#   - API_KEY como bloco: URL_API_KEY_SOMETHING
_SECRET_KEY_RE = re.compile(
    r"(_TOKEN|_KEY|_SECRET|_PASSWORD|_PASSWD|_DSN|_CERT|_CREDENTIAL)$"
    r"|PRIVATE"   # chaves privadas em qualquer posição
    r"|API_KEY"   # API_KEY como token de API
    r"|_SASL_PASSWORD"
, re.IGNORECASE)

# Valores que são considerados seguros (não são secrets expostos)
_SAFE_VALUE_PATTERNS = re.compile(
    r"^$"                              # vazio
    r"|^\s*$"                          # apenas espaços
    r"|^\$\{[A-Z_][A-Z0-9_]*\}$"      # ${VAR_NAME}
    r"|^\*+$"                          # placeholder ***
    r"|^/run/secrets/"                 # k8s secret mount
    r"|^/vault/"                       # vault mount
    r"|^#"                             # comentário (ex: no .env.example)
    r"|^dev-"                          # dev prefix placeholder
    r"|^placeholder"                   # placeholder explícito
    r"|^change.?me"                    # changeme, change_me
    r"|^replace.?me"                   # replace-me
    r"|^your[-_]"                      # your-secret-here
    r"|^<.+>$"                         # <SECRET_HERE>
    r"|^todo$"                         # todo
    r"|^xxx+$"                         # xxx, xxxx
, re.IGNORECASE)


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key))


def _is_safe_value(value: str) -> bool:
    return bool(_SAFE_VALUE_PATTERNS.match(value))


def _is_ref_value(value: str) -> bool:
    """Verifica se o valor já é uma referência ${VAR}."""
    return bool(re.match(r"^\$\{[A-Z_][A-Z0-9_]*\}$", value))


# ── audit_env_files ───────────────────────────────────────────────────────────

def audit_env_files(
    store: ServiceStore,
    *,
    directory: str,
    include_pattern: str = ".env*",
    check_registry_urls: bool = True,
) -> dict[str, Any]:
    """Escaneia todos os arquivos .env.* de um diretório e reporta problemas.

    Detecta:
    - Secrets hardcoded (valores não-vazios em vars *KEY, *SECRET, *PASSWORD, *TOKEN)
    - URLs que não batem com o registry (se check_registry_urls=True)
    - Vars ausentes em alguns perfis mas presentes em outros (cobertura cruzada)
    - Arquivos fora do padrão canônico de perfis

    Args:
        directory: Diretório a escanear (ex: '/path/to/platform-auth').
        include_pattern: Glob para os arquivos (default: '.env*').
        check_registry_urls: Verificar URLs contra o registry. Default: True.
    """
    base = Path(directory).expanduser().resolve()
    if not base.exists():
        return {"error": "DirectoryNotFound", "path": str(base)}

    # Perfis canônicos esperados
    canonical_profiles = {"local-dev", "local-hml", "cloud-dev", "cloud-hml", "cloud-prod"}

    # Arquivos utilitários conhecidos (não são perfis)
    utility_files = {".env", ".env.defaults", ".env.example", ".env.local.example",
                     ".env.local", ".env.lab", ".env.test"}

    files_found: list[dict] = []
    all_vars: dict[str, dict[str, str]] = {}   # {filename: {key: value}}
    hardcoded_secrets: list[dict] = []
    non_canonical: list[str] = []

    env_files = sorted(base.glob(include_pattern))
    if not env_files:
        return {"error": "NoEnvFilesFound", "directory": str(base), "pattern": include_pattern}

    for f in env_files:
        if f.is_dir():
            continue
        fname = f.name
        try:
            lines = _parse_env_file(f)
            variables = _lines_to_dict(lines)
        except Exception as exc:  # noqa: BLE001
            files_found.append({"file": fname, "error": str(exc)})
            continue

        all_vars[fname] = variables

        # Determina o perfil
        profile = fname.replace(".env.", "").replace(".env", "")
        is_utility = fname in utility_files or fname.endswith(".example")
        if not is_utility and profile not in canonical_profiles:
            non_canonical.append(fname)

        # Detecta secrets hardcoded
        for key, val in variables.items():
            if _is_secret_key(key) and val and not _is_safe_value(val):
                hardcoded_secrets.append({
                    "file": fname,
                    "key": key,
                    "value_preview": val[:8] + "..." if len(val) > 8 else val,
                    "suggested_ref": f"${{{key}}}",
                })

        files_found.append({
            "file": fname,
            "profile": profile if not is_utility else "utility",
            "var_count": len(variables),
            "has_hardcoded_secrets": any(
                s["file"] == fname for s in hardcoded_secrets
            ),
        })

    # Análise cross-profile: vars presentes em algum arquivo mas ausentes em outros
    # (considera apenas arquivos de perfil, não utilitários)
    profile_files = {
        fname: vars_
        for fname, vars_ in all_vars.items()
        if fname not in utility_files and not fname.endswith(".example")
    }

    all_keys: set[str] = set()
    for vars_ in profile_files.values():
        all_keys.update(vars_.keys())

    coverage_issues: list[dict] = []
    for key in sorted(all_keys):
        present_in = [f for f, v in profile_files.items() if key in v]
        absent_in = [f for f in profile_files if key not in f or key not in profile_files[f]]
        if absent_in and len(present_in) < len(profile_files):
            coverage_issues.append({
                "key": key,
                "present_in": present_in,
                "absent_in": absent_in,
            })

    # Verifica URLs contra registry
    url_issues: list[dict] = []
    if check_registry_urls:
        all_services = store.list_all()
        svc_by_name = {s["name"].lower(): s for s in all_services}

        for fname, variables in all_vars.items():
            for key, val in variables.items():
                if not key.startswith("URL_") or not val or _is_ref_value(val):
                    continue
                svc_suffix = key[4:].lower()
                svc = svc_by_name.get(svc_suffix) or svc_by_name.get(f"platform-{svc_suffix}")
                if svc:
                    base_url = (
                        svc.get("external_url") or svc.get("url")
                        or (f"http://{svc['host']}:{svc['port']}" if svc.get("host") and svc.get("port") else None)
                    )
                    if base_url:
                        existing_path = _extract_url_path(val)
                        expected = base_url.rstrip("/") + (existing_path if existing_path != "/" else "")
                        if val != expected:
                            url_issues.append({
                                "file": fname,
                                "key": key,
                                "current": val,
                                "expected": expected,
                                "service": svc["name"],
                            })

    _log.info(
        "audit_env_files dir=%s files=%d secrets=%d url_issues=%d",
        base, len(files_found), len(hardcoded_secrets), len(url_issues),
    )

    return {
        "directory": str(base),
        "files": files_found,
        "total_files": len(files_found),
        "non_canonical_files": non_canonical,
        "hardcoded_secrets": hardcoded_secrets,
        "hardcoded_secrets_count": len(hardcoded_secrets),
        "url_issues": url_issues,
        "url_issues_count": len(url_issues),
        "coverage_issues_count": len(coverage_issues),
        "coverage_issues": coverage_issues[:20],  # limita para não sobrecarregar
        "summary": {
            "ok": len(hardcoded_secrets) == 0 and len(url_issues) == 0,
            "action_required": (
                (["fix hardcoded secrets"] if hardcoded_secrets else [])
                + (["fix URL mismatches"] if url_issues else [])
                + (["review non-canonical files"] if non_canonical else [])
            ),
        },
    }


# ── redact_env_secrets ────────────────────────────────────────────────────────

def redact_env_secrets(
    _store: ServiceStore,
    *,
    paths: list[str],
    keys: list[str] | None = None,
    auto_detect: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Substitui valores hardcoded de secrets por ${VAR_NAME} em arquivos .env.

    Para cada variável identificada como secret com valor hardcoded, substitui
    por `${VAR_NAME}` — o valor real passa a vir do shell/CI/k8s como env var.

    Exemplo:
        JWT_SECRET_KEY=XrDsC...  ->  JWT_SECRET_KEY=${JWT_SECRET_KEY}
        DB_PASSWORD=toor         ->  DB_PASSWORD=${DB_PASSWORD}

    Args:
        paths: Lista de caminhos dos arquivos .env a processar.
        keys: Lista explícita de chaves a redact. Se None e auto_detect=True, detecta automaticamente.
        auto_detect: Detectar automaticamente vars *KEY, *SECRET, *PASSWORD, *TOKEN. Default: True.
        dry_run: Se True, apenas simula sem alterar arquivos. Default: False.
    """
    all_changes: list[dict] = []
    errors: list[dict] = []
    files_modified: list[str] = []

    explicit_keys = {k.upper() for k in keys} if keys else set()

    for raw_path in paths:
        p = Path(raw_path).expanduser()
        if not p.exists():
            errors.append({"file": raw_path, "error": "FileNotFound"})
            continue

        try:
            lines = _parse_env_file(p)
        except Exception as exc:  # noqa: BLE001
            errors.append({"file": raw_path, "error": str(exc)})
            continue

        file_changes: list[dict] = []
        new_lines: list[tuple[str, str]] = []

        for kind, raw in lines:
            if not kind.startswith("var:"):
                new_lines.append((kind, raw))
                continue

            key, _, val = raw.strip().partition("=")
            key = key.strip()
            val = val.strip()

            should_redact = (
                (auto_detect and _is_secret_key(key) and val and not _is_safe_value(val))
                or key.upper() in explicit_keys
            )

            if should_redact and not _is_ref_value(val) and val:
                ref_value = f"${{{key}}}"
                file_changes.append({
                    "file": p.name,
                    "key": key,
                    "old_value_preview": val[:8] + "..." if len(val) > 8 else val,
                    "new_value": ref_value,
                })
                new_lines.append((kind, f"{key}={ref_value}"))
            else:
                new_lines.append((kind, raw))

        if file_changes:
            all_changes.extend(file_changes)
            files_modified.append(str(p))
            if not dry_run:
                _write_env_lines(p, new_lines)
                _log.info("redact_env_secrets: %s — %d vars redacted", p.name, len(file_changes))

    return {
        "dry_run": dry_run,
        "files_processed": len(paths),
        "files_modified": files_modified,
        "total_changes": len(all_changes),
        "changes": all_changes,
        "errors": errors,
        "note": (
            "Valores substituidos por ${VAR_NAME}. "
            "Defina as vars no shell (export JWT_SECRET_KEY=...) ou no CI/CD secrets antes de rodar."
        ) if all_changes and not dry_run else (
            "dry_run=True: nenhum arquivo foi alterado." if dry_run else "Nenhuma mudanca necessaria."
        ),
    }
