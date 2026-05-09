"""pr_validate.py — variante de precommit_validate.py para contexto de PR.

Diferenças:
- Diff vem do range `base..HEAD` em vez do staged.
- Output adicional: comentário markdown formatado para `gh pr comment`.
- Quando rodando em GitHub Actions, lê `GITHUB_BASE_REF` / `GITHUB_HEAD_REF`
  e usa `gh` CLI para postar o comentário.
- Exit code: 0 (OK ou WARN), 1 (BLOCK) — o workflow decide se isso falha o
  check ou só vira comentário não-bloqueante.

Uso local:
    python scripts/pr_validate.py --base main --head HEAD
    python scripts/pr_validate.py --base origin/main --post-comment

Uso em GitHub Actions:
    python scripts/pr_validate.py --post-comment
    # Variáveis GITHUB_BASE_REF, GITHUB_HEAD_REF, GITHUB_REPOSITORY,
    # PR_NUMBER são lidas automaticamente.

A lógica de detecção (flags, layers) é reutilizada de precommit_validate.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

# Reutiliza heurísticas e helpers do hook de pre-commit.
# Tenta import via pacote instalado (scripts.*) ou fallback para o diretório local,
# que é o modo usado em execução direta do script (python scripts/pr_validate.py).
try:
    from scripts import precommit_validate as core  # pacote instalado
except ImportError:
    SCRIPTS_DIR = Path(__file__).resolve().parent
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import precommit_validate as core  # execução direta  # noqa: E402


def _git(args: list[str]) -> str:
    """Wrapper de git, retorna stdout ou string vazia em erro."""
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


def _resolve_base_sha(base_ref: str) -> str:
    """Resolve a ref base para SHA. Lida com remote refs (origin/main)."""
    sha = _git(["rev-parse", base_ref]).strip()
    return sha


def _diff_range(base: str, head: str) -> str:
    """Diff entre base..head, com unified=2."""
    out = _git(["diff", "--unified=2", f"{base}..{head}"])
    if len(out) > core._MAX_DIFF_CHARS:
        out = out[: core._MAX_DIFF_CHARS] + "\n…(truncated)"
    return out


def _files_changed(base: str, head: str) -> list[str]:
    out = _git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}..{head}"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _commit_messages(base: str, head: str) -> str:
    """Junta os subjects dos commits do range, separados por ' | '."""
    out = _git(["log", "--pretty=%s", f"{base}..{head}"])
    subjects = [s.strip() for s in out.splitlines() if s.strip()]
    return " | ".join(subjects[:10])  # limite defensivo


def _format_comment(payload: dict, result: dict) -> str:
    """Renderiza o resultado da validação como comentário markdown para o PR."""
    risk = result.get("risk_level", "unknown")
    approved = result.get("approved", True)
    violations = result.get("violations", [])
    actions = result.get("required_actions", [])
    recs = result.get("recommendations", [])
    notes = result.get("notes", [])

    if approved is False or risk == "critical":
        header_emoji = "🛑"
        verdict = "**BLOCKED**"
    elif risk == "high":
        header_emoji = "⚠️"
        verdict = "**HIGH RISK**"
    elif risk == "medium":
        header_emoji = "⚠️"
        verdict = "**Medium risk**"
    else:
        header_emoji = "✅"
        verdict = "**OK**"

    lines = [
        f"## {header_emoji} ai-governance MCP — PR validation",
        "",
        f"{verdict} · `risk_level={risk}`",
        "",
        f"- Files: {payload.get('affected_files_count') or len(payload.get('affected_files', []))}",
        f"- Layers: {', '.join(payload.get('affected_layers') or []) or '(none detected)'}",
        "",
    ]

    if violations:
        lines.append("### Violations")
        for v in violations:
            lines.append(f"- {v}")
        lines.append("")

    if actions:
        lines.append("### Required actions")
        for a in actions:
            lines.append(f"- {a}")
        lines.append("")

    if recs:
        lines.append("### Recommendations")
        for r in recs:
            lines.append(f"- {r}")
        lines.append("")

    if notes:
        lines.append("### Notes")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.append(
        "<sub>Posted by `pr_validate.py` invoking `validate_agent_decision` "
        "via the [ai-governance-mcp-server](../tree/main/ai-governance-mcp-server). "
        "Adjust `ecosystem.yaml` / knowledge-base if any of the above is wrong.</sub>"
    )
    return "\n".join(lines)


def _post_comment(comment: str, pr_number: str | None = None) -> bool:
    """Posta comentário no PR via gh CLI. Retorna True se sucesso."""
    if pr_number is None:
        pr_number = os.environ.get("PR_NUMBER", "")
    if not pr_number:
        # Fallback: usa GITHUB_REF (refs/pull/123/merge) para extrair o número.
        ref = os.environ.get("GITHUB_REF", "")
        if "/pull/" in ref:
            pr_number = ref.split("/pull/", 1)[1].split("/", 1)[0]

    if not pr_number:
        print(
            "[pr-validate] WARN: PR_NUMBER não detectado; pulando post.",
            file=sys.stderr,
        )
        return False

    try:
        proc = subprocess.run(
            ["gh", "pr", "comment", pr_number, "--body", comment],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            print(
                f"[pr-validate] WARN: gh pr comment falhou: {proc.stderr.strip()}",
                file=sys.stderr,
            )
            return False
        return True
    except FileNotFoundError:
        print("[pr-validate] WARN: gh CLI não encontrada — pulando post.", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        default=os.environ.get("GITHUB_BASE_REF") or "main",
        help="Ref base do PR (default: GITHUB_BASE_REF env ou 'main').",
    )
    parser.add_argument(
        "--head",
        default=os.environ.get("GITHUB_HEAD_REF") or "HEAD",
        help="Ref head do PR (default: GITHUB_HEAD_REF env ou 'HEAD').",
    )
    parser.add_argument(
        "--post-comment",
        action="store_true",
        help="Posta o resultado como comentário no PR via gh CLI.",
    )
    parser.add_argument(
        "--pr-number",
        default=None,
        help="PR number para post (default: env PR_NUMBER ou parsed de GITHUB_REF).",
    )
    parser.add_argument(
        "--block-on-high",
        action="store_true",
        default=os.environ.get("PR_VALIDATE_BLOCK_ON_HIGH") == "1",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Imprime payload sem invocar MCP nem postar.",
    )
    parser.add_argument(
        "--output-comment",
        type=Path,
        default=None,
        help="Salva o comentário renderizado em arquivo (em vez de postar).",
    )
    args = parser.parse_args()

    # Tenta resolver base como remote ref se o local não existe.
    base_sha = _resolve_base_sha(args.base) or args.base
    head_sha = _resolve_base_sha(args.head) or args.head

    files = _files_changed(base_sha, head_sha)
    if not files:
        print("[pr-validate] no files changed; nothing to do.", file=sys.stderr)
        return 0

    if len(files) > core._MAX_FILES * 4:
        # PR pode ter mais arquivos que commit; limite mais alto, mas não infinito.
        print(
            f"[pr-validate] WARN: {len(files)} arquivos no PR — pode estar grande demais para um único PR.",
            file=sys.stderr,
        )

    diff = _diff_range(base_sha, head_sha)
    flags = core._detect_flags(diff, files)
    layers = core._detect_layers(files)

    repo_name = os.environ.get("PRECOMMIT_REPO_NAME") or core._repo_name()
    task_description = (
        os.environ.get("PRECOMMIT_TASK_DESCRIPTION")
        or _commit_messages(base_sha, head_sha)
        or f"PR validation of {head_sha[:7]} against {base_sha[:7]}"
    )

    payload = {
        "repository_name": repo_name,
        "task_description": task_description,
        "proposed_change": diff or "(no diff content)",
        "affected_files": files,
        "affected_layers": layers,
        **flags,
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    try:
        result = asyncio.run(core._validate_via_mcp(payload))
    except Exception as e:  # noqa: BLE001
        print(f"[pr-validate] WARN: validate skipped (server error: {e})", file=sys.stderr)
        return 0

    if "error" in result:
        print(
            f"[pr-validate] WARN: tool error: {result.get('details', result)}",
            file=sys.stderr,
        )
        return 0

    comment = _format_comment(payload, result)

    if args.output_comment:
        args.output_comment.write_text(comment, encoding="utf-8")
        print(f"[pr-validate] comment saved to {args.output_comment}", file=sys.stderr)
    else:
        # Sempre imprime o comentário em stdout para visibilidade no log do CI.
        print(comment)

    if args.post_comment:
        _post_comment(comment, pr_number=args.pr_number)

    # Exit code segue a mesma matriz do hook de pre-commit.
    return core._print_result(result, block_on_high=args.block_on_high)


if __name__ == "__main__":
    sys.exit(main())
