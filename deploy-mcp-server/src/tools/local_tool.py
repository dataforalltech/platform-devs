"""Ferramentas de gerenciamento de repositorios locais.

Tools
-----
- get_repos_root    : retorna o caminho da pasta de repos (env var / config-mcp / fallback)
- set_repos_root    : define REPOS_ROOT no config-mcp e opcionalmente cria o diretorio
- list_local_repos  : lista repos clonados em REPOS_ROOT com branch atual, remote e ultimo commit
- clone_repo        : clona um repo do GitHub para dentro de REPOS_ROOT

Resolucao de REPOS_ROOT (ordem de prioridade)
---------------------------------------------
1. Argumento explicito passado na chamada da tool
2. DEPLOY_REPOS_ROOT (env var lida pelo DeploySettings)
3. REPOS_ROOT / WORKSPACE_REPOS_ROOT (env vars genericas)
4. config-mcp namespace workspace, chave REPOS_ROOT (via ConfigClient HTTP)
5. Auto-deteccao: diretorios comuns (~/repos, ~/repositorios, ~/projects, ~/code)
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from ..config.settings import DeploySettings
from ..knowledge.github_client import GitHubClient, GitHubClientError

_log = logging.getLogger(__name__)

# Candidatos para auto-deteccao de repos_root
_AUTO_DETECT_CANDIDATES = [
    "~/repos",
    "~/repositorios",
    "~/projects",
    "~/code",
    "~/workspace",
    "~/src",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_git(args: list[str], cwd: Path, timeout: int = 10) -> tuple[bool, str]:
    """Executa um comando git em cwd. Retorna (sucesso, output)."""
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, timeout=timeout, cwd=str(cwd),
        )
        return r.returncode == 0, (r.stdout.strip() or r.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _git_info(repo_path: Path) -> dict[str, Any]:
    """Coleta informacoes git de um repositorio local."""
    ok, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    branch = branch if ok else "unknown"

    ok, remote = _run_git(["remote", "get-url", "origin"], repo_path)
    remote = remote if ok else None

    ok, last_commit = _run_git(
        ["log", "-1", "--format=%h %s (%ar)", "--no-merges"], repo_path
    )
    last_commit = last_commit if ok else None

    ok, status_out = _run_git(["status", "--porcelain"], repo_path)
    dirty = bool(status_out) if ok else None

    ok, tag = _run_git(["describe", "--tags", "--abbrev=0"], repo_path)
    latest_tag = tag if ok else None

    return {
        "branch": branch,
        "remote": remote,
        "last_commit": last_commit,
        "dirty": dirty,
        "latest_tag": latest_tag,
    }


def _resolve_repos_root(
    settings: DeploySettings,
    explicit: str | None = None,
) -> Path | None:
    """Resolve REPOS_ROOT seguindo a ordem de prioridade."""
    # 1. Argumento explicito
    if explicit:
        return Path(explicit).expanduser().resolve()

    # 2-3. Settings (inclui DEPLOY_REPOS_ROOT + env vars genericas)
    from_settings = settings.get_repos_root_path()
    if from_settings:
        return from_settings

    # 4. config-mcp via HTTP
    try:
        from shared.config_client import ConfigClient
        client = ConfigClient.from_env()
        ws = client.get_workspace_config()
        repos_root_val = ws.get("REPOS_ROOT") or (ws.get("config") or {}).get("REPOS_ROOT", {}).get("value")
        if repos_root_val:
            return Path(repos_root_val).expanduser().resolve()
    except Exception as exc:
        _log.debug("config_mcp_repos_root_unavailable: %s", exc)

    # 5. Auto-deteccao
    for candidate in _AUTO_DETECT_CANDIDATES:
        p = Path(candidate).expanduser()
        if p.exists() and p.is_dir():
            return p

    return None


def _push_repos_root_to_config_mcp(path: str) -> bool:
    """Persiste REPOS_ROOT no config-mcp. Retorna True se ok."""
    try:
        from shared.config_client import ConfigClient
        import httpx
        client = ConfigClient.from_env()
        # Chama set_workspace_config via HTTP
        resp = httpx.post(
            f"{client.base_url}/v1/tools/set_workspace_config",
            json={"key": "REPOS_ROOT", "value": path, "create_dir": False},
            timeout=5.0,
        )
        return resp.status_code < 400
    except Exception as exc:
        _log.warning("config_mcp_set_repos_root_failed: %s", exc)
        return False


# ── Tools ─────────────────────────────────────────────────────────────────────

def get_repos_root(
    settings: DeploySettings,
    *,
    explicit: str | None = None,
) -> dict[str, Any]:
    """Retorna o caminho resolvido de REPOS_ROOT e a fonte da configuracao."""
    resolved = _resolve_repos_root(settings, explicit)

    if resolved is None:
        return {
            "repos_root": None,
            "exists": False,
            "source": None,
            "tip": (
                "REPOS_ROOT nao configurado. Use set_repos_root para definir a pasta "
                "ou exporte DEPLOY_REPOS_ROOT=<caminho> no shell."
            ),
        }

    # Determina fonte
    if explicit:
        source = "argument"
    elif settings.repos_root:
        source = "DEPLOY_REPOS_ROOT"
    else:
        source = "auto_detected_or_config_mcp"

    exists = resolved.exists()
    repo_count = sum(1 for p in resolved.iterdir() if p.is_dir() and (p / ".git").exists()) if exists else 0

    return {
        "repos_root": str(resolved),
        "exists": exists,
        "source": source,
        "repo_count": repo_count,
    }


def set_repos_root(
    settings: DeploySettings,
    *,
    path: str,
    create_dir: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    """Define REPOS_ROOT no config-mcp e opcionalmente cria o diretorio.

    persist=True (default): salva no config-mcp namespace workspace.REPOS_ROOT.
    create_dir=True: cria o diretorio se nao existir.
    """
    resolved = Path(path).expanduser().resolve()

    if not resolved.exists():
        if create_dir:
            resolved.mkdir(parents=True, exist_ok=True)
            _log.info("repos_root_created path=%s", resolved)
        else:
            return {
                "error": f"Diretorio nao existe: {resolved}",
                "tip": "Use create_dir=true para criar automaticamente.",
                "path": str(resolved),
            }

    if not resolved.is_dir():
        return {"error": f"Caminho existe mas nao e um diretorio: {resolved}"}

    persisted = False
    if persist:
        persisted = _push_repos_root_to_config_mcp(str(resolved))

    return {
        "repos_root": str(resolved),
        "created": create_dir and resolved.exists(),
        "persisted_to_config_mcp": persisted,
        "action": "set",
        "tip": (
            None if persisted else
            "config-mcp nao disponivel — defina DEPLOY_REPOS_ROOT no shell para persistir localmente."
        ),
    }


def list_local_repos(
    settings: DeploySettings,
    *,
    repos_root: str | None = None,
    filter_name: str | None = None,
    include_git_info: bool = True,
) -> dict[str, Any]:
    """Lista repositorios clonados em REPOS_ROOT.

    Para cada subdiretorio com .git retorna: branch atual, remote origin,
    ultimo commit, status dirty, latest tag.

    filter_name: substring case-insensitive no nome do repo.
    include_git_info: se False, retorna apenas nomes (mais rapido).
    """
    root = _resolve_repos_root(settings, repos_root)
    if root is None:
        return {
            "error": "REPOS_ROOT nao configurado.",
            "tip": "Use set_repos_root ou exporte DEPLOY_REPOS_ROOT=<caminho>.",
        }

    if not root.exists():
        return {
            "error": f"Diretorio nao existe: {root}",
            "repos_root": str(root),
        }

    repos: list[dict] = []
    non_repos: list[str] = []

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if filter_name and filter_name.lower() not in entry.name.lower():
            continue

        git_dir = entry / ".git"
        if not git_dir.exists():
            non_repos.append(entry.name)
            continue

        info: dict[str, Any] = {
            "name": entry.name,
            "path": str(entry),
            "has_git": True,
        }
        if include_git_info:
            info.update(_git_info(entry))

        repos.append(info)

    return {
        "repos_root": str(root),
        "repos": repos,
        "total": len(repos),
        "non_repos_dirs": non_repos,
    }


def clone_repo(
    client: GitHubClient,
    settings: DeploySettings,
    *,
    repo: str,
    branch: str | None = None,
    repos_root: str | None = None,
    target_dir: str | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Clona um repositorio do GitHub para REPOS_ROOT/<repo_name>.

    repo: nome simples ('platform-auth') ou 'owner/repo'.
    branch: branch/tag/SHA a fazer checkout. Default: branch padrao do repo.
    target_dir: nome do diretorio destino. Default: nome do repo sem owner/.
    depth: shallow clone (--depth N). None = clone completo.
    """
    root = _resolve_repos_root(settings, repos_root)
    if root is None:
        return {
            "error": "REPOS_ROOT nao configurado.",
            "tip": "Use set_repos_root ou exporte DEPLOY_REPOS_ROOT=<caminho>.",
        }

    if not root.exists():
        return {"error": f"REPOS_ROOT nao existe: {root}"}

    # Normaliza repo para owner/name
    if "/" not in repo:
        full_repo = f"{settings.github_org}/{repo}"
    else:
        full_repo = repo

    repo_name = full_repo.split("/")[-1]
    dest_name = target_dir or repo_name
    dest_path = root / dest_name

    if dest_path.exists():
        return {
            "error": f"Destino ja existe: {dest_path}",
            "tip": f"Use target_dir para clonar com outro nome ou remova {dest_path} antes.",
            "path": str(dest_path),
        }

    # Monta URL de clone com token
    token = settings.github_token
    clone_url = f"https://{token}@github.com/{full_repo}.git"

    git_cmd = ["git", "clone"]
    if depth:
        git_cmd += ["--depth", str(depth)]
    if branch:
        git_cmd += ["--branch", branch, "--single-branch"]
    git_cmd += [clone_url, str(dest_path)]

    _log.info("clone_repo repo=%s dest=%s", full_repo, dest_path)

    try:
        result = subprocess.run(
            git_cmd,
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"error": "git clone timeout (120s)", "repo": full_repo}
    except FileNotFoundError:
        return {"error": "git nao encontrado no PATH"}

    if result.returncode != 0:
        # Remove token da mensagem de erro
        err_msg = result.stderr.replace(token, "***") if token else result.stderr
        return {
            "error": "git clone falhou",
            "details": err_msg.strip(),
            "repo": full_repo,
        }

    # Coleta info do repo clonado
    git_info = _git_info(dest_path)

    return {
        "repo": full_repo,
        "path": str(dest_path),
        "branch": git_info.get("branch"),
        "remote": f"https://github.com/{full_repo}.git",  # sem token
        "last_commit": git_info.get("last_commit"),
        "repos_root": str(root),
        "action": "cloned",
    }
