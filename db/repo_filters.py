"""
Filtros canônicos de repositórios — Governança & Segurança

REGRA OBRIGATÓRIA (ADR-002):
  Toda operação automatizada (CI, CD, clone, sync, build, ACR push) deve usar
  SOMENTE repositórios que satisfazem:

      active = true AND allows_automation = true

  Repositórios com allows_automation = false foram explicitamente excluídos
  pelo time de plataforma. Ignorar esse filtro é uma violação de governança
  e pode resultar em builds indevidos, exposição de credenciais ACR ou
  modificação de repos legados/depreciados.

COMO USAR:
    from repo_filters import get_automation_repos, AUTOMATION_FILTER_SQL

    # Em queries SQL diretas:
    cur.execute(f"SELECT id, name FROM repositories {AUTOMATION_FILTER_SQL}")

    # Para obter lista Python pronta:
    repos = get_automation_repos(conn)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# ── SQL canônico ────────────────────────────────────────────────────────────── #

AUTOMATION_FILTER_SQL = "WHERE active = true AND allows_automation = true"
AUTOMATION_FILTER_SQL_AND = "AND active = true AND allows_automation = true"

POSTGRES_CONFIG: dict[str, Any] = {
    "host": os.getenv("POSTGRES_HOST", "claude-dev"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "postgres_password_local_dev"),
    "database": os.getenv("POSTGRES_DB", "app"),
}

REPOS_DIR = Path(os.getenv("PLATFORM_REPOS_DIR", os.path.expanduser("~/repos")))
ORG = "dataforalltech"


def get_automation_repos(conn) -> list[dict]:
    """Retorna todos os repos elegíveis para automação.

    Filtro obrigatório: active = true AND allows_automation = true.
    Nunca opere em repos fora desse conjunto sem aprovação explícita.

    Returns:
        Lista de dicts com id, name, repo_type, repo_scope, path.
    """
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, name, repo_type, repo_scope
        FROM repositories
        {AUTOMATION_FILTER_SQL}
        ORDER BY repo_type, name
    """)
    repos = [
        {
            "id": row[0],
            "name": row[1],
            "repo_type": row[2],
            "repo_scope": row[3],
            "path": REPOS_DIR / row[1],
        }
        for row in cur.fetchall()
    ]
    cur.close()
    return repos


def get_automation_repo_names(conn) -> list[str]:
    """Retorna apenas os nomes dos repos elegíveis para automação."""
    return [r["name"] for r in get_automation_repos(conn)]


def assert_repo_allowed(conn, repo_name: str) -> None:
    """Valida que um repo específico está no escopo de automação.

    Raises:
        PermissionError: se o repo não está elegível para automação.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT allows_automation, active FROM repositories WHERE name = %s",
        (repo_name,),
    )
    row = cur.fetchone()
    cur.close()

    if row is None:
        raise PermissionError(
            f"Repo '{repo_name}' não encontrado no banco. "
            "Sincronize primeiro com sync_github_to_postgres.py."
        )
    allows, active = row
    if not active:
        raise PermissionError(
            f"Repo '{repo_name}' está inativo (active=false). "
            "Operações automáticas não são permitidas."
        )
    if not allows:
        raise PermissionError(
            f"Repo '{repo_name}' tem allows_automation=false. "
            "Esse repo foi explicitamente excluído da automação — "
            "consulte automation_notes na tabela repositories para o motivo."
        )
