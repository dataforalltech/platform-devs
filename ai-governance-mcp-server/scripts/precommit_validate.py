"""precommit_validate.py — pre-commit hook que chama validate_agent_decision.

Reúne sinais do diff staged (arquivos, conteúdo das edits) e invoca a tool
`validate_agent_decision` via stdio MCP. Bloqueia o commit (exit 1) se a
validação reprovar com `approved=false` ou `risk_level=critical`. Avisa
(stdout + exit 0) em casos `high`/`medium` — não bloqueia, mas o agente vê.

Modo de uso (manual):
    python scripts/precommit_validate.py

Como hook git tradicional (.git/hooks/pre-commit):
    #!/bin/bash
    exec python /caminho/para/scripts/precommit_validate.py

Variáveis de ambiente:
    PRECOMMIT_REPO_NAME — nome do repo (default: basename do toplevel git).
    PRECOMMIT_BLOCK_ON_HIGH=1 — bloqueia também em risk=high (default: só critical).
    PRECOMMIT_TASK_DESCRIPTION — força uma descrição específica (default: derivado de HEAD).

Importante:
    - Hook é "best effort" — se o MCP server não puder ser spawned, devolve
      warning não-bloqueante.
    - Não roda em --amend / merge / rebase para evitar duplo trabalho.
    - Limita o conteúdo do diff a 8000 chars para não estourar a description.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

# Limites
_MAX_DIFF_CHARS = 8000
_MAX_FILES = 50


def _git(args: list[str]) -> str:
    """Roda git com args dado, devolve stdout. Falha silenciosa = string vazia."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _is_special_commit() -> bool:
    """Detecta commits especiais (merge, rebase, amend) onde o hook não deve rodar."""
    git_dir = Path(_git(["rev-parse", "--git-dir"]).strip() or ".git")
    if (git_dir / "MERGE_HEAD").exists():
        return True
    if (git_dir / "REBASE_HEAD").exists():
        return True
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        return True
    return False


def _staged_files() -> list[str]:
    out = _git(["diff", "--name-only", "--cached", "--diff-filter=ACMR"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _staged_diff(limit_chars: int = _MAX_DIFF_CHARS) -> str:
    out = _git(["diff", "--cached", "--unified=2"])
    if len(out) > limit_chars:
        out = out[:limit_chars] + "\n…(truncated)"
    return out


def _detect_layers(files: list[str]) -> list[str]:
    """Heurística simples: mapeia paths para camadas declaradas no AGENTS.md."""
    layers: set[str] = set()
    for path in files:
        low = path.lower()
        if "/migrations/" in low or "alembic/" in low or low.endswith(".sql"):
            layers.add("database")
        if any(seg in low for seg in ("/handlers/", "/services/", "app/", "src/server", "/api/")):
            layers.add("backend")
        if any(seg in low for seg in ("frontend/", "/components/", ".tsx", ".jsx", "webapp")):
            layers.add("frontend")
        if any(seg in low for seg in ("dockerfile", "compose", "k8s", "helm", "infra/", "ci.yml")):
            layers.add("infrastructure")
        if "tests/" in low or low.startswith("test_") or "test_" in low.split("/")[-1]:
            layers.add("testing")
        if any(seg in low for seg in ("auth", "jwt", "secret", "credential")):
            layers.add("security")
        if any(seg in low for seg in ("logger", "metric", "trace", "observability")):
            layers.add("observability")
        if any(seg in low for seg in ("provider", "client", "integration", "/clients/")):
            layers.add("integrations")
    return sorted(layers)


def _detect_flags(diff: str, files: list[str]) -> dict:
    """Detecta apenas flags com sinal de alta confiança baseados em path.

    Os flags booleanos do validator (adds_fallback, changes_contracts,
    modifies_security) disparam checagens adicionais que ASSUMEM que o agente
    está consciente da mudança. Inferir esses flags por palavra-chave em diff
    de hook gera falso positivo demais (ex.: docstring com 'fallback', regex
    que casa 'pyproject.toml' em string literal). Por isso, mantemos apenas
    `adds_dependency` aqui — sinal estável baseado no nome do arquivo.

    Os outros padrões (silent fallback, hardcoded creds, auth bypass) já são
    detectados pelo VALIDATOR via regex no `proposed_change` text. Não
    precisamos duplicar essa lógica aqui.
    """
    file_names = {Path(p).name for p in files}
    adds_dependency = bool(
        file_names & {"pyproject.toml", "requirements.txt", "package.json", "poetry.lock"}
    )
    return {
        "changes_contracts": False,
        "adds_fallback": False,
        "adds_dependency": adds_dependency,
        "modifies_security": False,
    }


def _repo_name() -> str:
    explicit = os.environ.get("PRECOMMIT_REPO_NAME")
    if explicit:
        return explicit
    toplevel = _git(["rev-parse", "--show-toplevel"]).strip()
    if toplevel:
        return Path(toplevel).name
    return "unknown-repo"


def _task_description(files: list[str]) -> str:
    explicit = os.environ.get("PRECOMMIT_TASK_DESCRIPTION")
    if explicit:
        return explicit
    head_subject = _git(["log", "-1", "--pretty=%s"]).strip()
    summary = head_subject or "Pre-commit validation of staged changes"
    if files:
        summary += f" (touching {len(files)} files)"
    return summary


# ---------------------------------------------------------------------- #
# Invocação MCP                                                           #
# ---------------------------------------------------------------------- #
async def _validate_via_mcp(payload: dict) -> dict:
    """Invoca validate_agent_decision via stdio MCP, devolve o JSON."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    project_root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.server.mcp_server"],
        env={
            **os.environ,
            "GOVERNANCE_KB_PATH": str(project_root / "knowledge-base"),
            "PYTHONPATH": str(project_root),
        },
        cwd=str(project_root),
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("validate_agent_decision", payload)
            return json.loads(result.content[0].text)


def _print_result(result: dict, block_on_high: bool) -> int:
    risk = result.get("risk_level", "unknown")
    approved = result.get("approved", True)
    violations = result.get("violations", [])
    actions = result.get("required_actions", [])
    recs = result.get("recommendations", [])

    indicator = "OK"
    if approved is False or risk == "critical":
        indicator = "BLOCK"
    elif risk == "high":
        indicator = "BLOCK" if block_on_high else "WARN"
    elif risk == "medium":
        indicator = "WARN"

    print(f"[ai-governance pre-commit] {indicator} risk={risk}", file=sys.stderr)
    if violations:
        print("  violations:", file=sys.stderr)
        for v in violations:
            print(f"    - {v}", file=sys.stderr)
    if actions:
        print("  required actions:", file=sys.stderr)
        for a in actions:
            print(f"    - {a}", file=sys.stderr)
    if recs and indicator != "OK":
        print("  recommendations:", file=sys.stderr)
        for r in recs:
            print(f"    - {r}", file=sys.stderr)

    if indicator == "BLOCK":
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--block-on-high",
        action="store_true",
        default=os.environ.get("PRECOMMIT_BLOCK_ON_HIGH") == "1",
        help="Bloqueia também em risk=high (default: só critical).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Não invoca MCP — só imprime o payload que seria enviado.",
    )
    args = parser.parse_args()

    if _is_special_commit():
        # Não roda em merge/rebase/amend — evita duplo trabalho e falsos positivos.
        return 0

    files = _staged_files()
    if not files:
        return 0

    if len(files) > _MAX_FILES:
        print(
            f"[ai-governance pre-commit] WARN: {len(files)} arquivos staged > limite "
            f"{_MAX_FILES}; pulando validação. Considere splitar o commit.",
            file=sys.stderr,
        )
        return 0

    diff = _staged_diff()
    flags = _detect_flags(diff, files)
    layers = _detect_layers(files)

    payload = {
        "repository_name": _repo_name(),
        "task_description": _task_description(files),
        "proposed_change": diff or "(no diff content captured)",
        "affected_files": files,
        "affected_layers": layers,
        **flags,
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    try:
        result = asyncio.run(_validate_via_mcp(payload))
    except Exception as e:  # noqa: BLE001
        # Hook nunca deve quebrar o commit por causa de falha de transporte.
        print(
            f"[ai-governance pre-commit] WARN: validate skipped (server unavailable: {e})",
            file=sys.stderr,
        )
        return 0

    if "error" in result:
        print(
            f"[ai-governance pre-commit] WARN: tool error: {result.get('details', result)}",
            file=sys.stderr,
        )
        return 0

    return _print_result(result, block_on_high=args.block_on_high)


if __name__ == "__main__":
    sys.exit(main())
