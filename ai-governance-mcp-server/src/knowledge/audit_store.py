"""audit_store.py — trilha de auditoria persistente para validate_agent_decision.

Armazena cada chamada bem-sucedida ao validate_agent_decision em um arquivo JSONL
(JSON Lines), uma entrada por linha, append-only. Isso permite:

  - Rastrear quem pediu o quê e qual foi o veredicto.
  - Auditar padrões de uso (repos que mais disparam violations, risk_level acima de low, etc.).
  - Suporte a homologação e revisão de governança.

Formato de cada linha:
  {
    "ts"               : "2026-05-05T12:00:00.123456Z",
    "repo"             : "platform-auth",
    "task_description" : "Adicionar endpoint de login" (primeiros 200 chars),
    "approved"         : true,
    "risk_level"       : "low",
    "violations_count" : 0,
    "violations"       : [],
    "required_actions_count": 0,
    "required_actions" : [],
    "affected_layers"  : ["backend"],
    "affected_files_count": 3,
    "flags"            : {"changes_contracts": false, ...}
  }

Thread-safety: escritas são atômicas via lock de arquivo (portlock). Como o
servidor MCP é single-threaded (asyncio), isso é precaução para futura concorrência.

Configuração:
  GOVERNANCE_AUDIT_PATH=./audit/decisions.jsonl
  Se não configurado: <kb_path>/audit/decisions.jsonl
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()


class AuditStore:
    """Persiste e consulta registros de auditoria de decisões do agente."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Escrita                                                              #
    # ------------------------------------------------------------------ #

    def record(self, result: dict, input_summary: dict | None = None) -> None:
        """Persiste um resultado de validate_agent_decision no log de auditoria.

        Args:
            result:        Retorno completo de validate_agent_decision.
            input_summary: Subdicionário `input_summary` dentro do result.
                           Usado para extrair repo, layers, flags, etc.
        """
        summary = input_summary or result.get("input_summary", {})
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "repo": summary.get("repository_name", "unknown"),
            "task_description": (summary.get("task_description") or "")[:200],
            "approved": result.get("approved", True),
            "risk_level": result.get("risk_level", "unknown"),
            "violations_count": len(result.get("violations", [])),
            "violations": result.get("violations", []),
            "required_actions_count": len(result.get("required_actions", [])),
            "required_actions": result.get("required_actions", []),
            "affected_layers": summary.get("affected_layers", []),
            "affected_files_count": summary.get("affected_files_count", 0),
            "flags": {
                "changes_contracts": summary.get("changes_contracts", False),
                "adds_fallback": summary.get("adds_fallback", False),
                "adds_dependency": summary.get("adds_dependency", False),
                "modifies_security": summary.get("modifies_security", False),
            },
        }
        line = json.dumps(entry, ensure_ascii=False)
        with _lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    # ------------------------------------------------------------------ #
    # Leitura / consulta                                                   #
    # ------------------------------------------------------------------ #

    def query(
        self,
        *,
        repo: str | None = None,
        risk_level: str | None = None,
        approved: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Devolve entradas filtradas em ordem cronológica reversa (mais recente primeiro).

        Args:
            repo:       Filtro por repositório (substring case-insensitive).
            risk_level: Filtro exato por nível de risco (low/medium/high/critical).
            approved:   Filtro por veredicto (True=aprovado, False=bloqueado).
            limit:      Máximo de registros devolvidos (default 50, máximo 500).
            offset:     Pular os primeiros N resultados (paginação).
        """
        if not self.path.exists():
            return []

        limit = min(limit, 500)
        entries: list[dict] = []

        with _lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if repo and repo.lower() not in entry.get("repo", "").lower():
                continue
            if risk_level and entry.get("risk_level") != risk_level:
                continue
            if approved is not None and entry.get("approved") != approved:
                continue
            entries.append(entry)

        # Inverter (mais recente primeiro), paginar.
        entries.reverse()
        return entries[offset: offset + limit]

    def stats(self) -> dict:
        """Estatísticas agregadas da trilha de auditoria."""
        if not self.path.exists():
            return {
                "total": 0,
                "approved": 0,
                "blocked": 0,
                "by_risk_level": {},
                "top_repos": [],
                "top_violations": [],
            }

        total = 0
        approved_count = 0
        blocked_count = 0
        risk_counts: dict[str, int] = {}
        repo_counts: dict[str, int] = {}
        violation_counts: dict[str, int] = {}

        with _lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            total += 1
            if entry.get("approved"):
                approved_count += 1
            else:
                blocked_count += 1

            risk = entry.get("risk_level", "unknown")
            risk_counts[risk] = risk_counts.get(risk, 0) + 1

            repo = entry.get("repo", "unknown")
            repo_counts[repo] = repo_counts.get(repo, 0) + 1

            for v in entry.get("violations", []):
                # Usa os primeiros 80 chars como chave de agrupamento.
                key = v[:80]
                violation_counts[key] = violation_counts.get(key, 0) + 1

        top_repos = sorted(repo_counts.items(), key=lambda x: -x[1])[:10]
        top_violations = sorted(violation_counts.items(), key=lambda x: -x[1])[:10]

        return {
            "total": total,
            "approved": approved_count,
            "blocked": blocked_count,
            "block_rate": round(blocked_count / total, 3) if total else 0.0,
            "by_risk_level": risk_counts,
            "top_repos": [{"repo": r, "count": c} for r, c in top_repos],
            "top_violations": [{"violation": v, "count": c} for v, c in top_violations],
        }
