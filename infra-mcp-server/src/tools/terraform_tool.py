"""Tools terraform: validate, fmt-check, plan, show-plan."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config.settings import Settings
from ..utils.subprocess_runner import (
    BinaryNotFound,
    CommandTimeout,
    run_command,
)
from ..utils.validators import normalize_path

# Regex defensivo para parsing do summary do terraform plan
# Match exemplo: "Plan: 3 to add, 1 to change, 0 to destroy."
_PLAN_SUMMARY_RE = re.compile(
    r"Plan:\s+(\d+)\s+to\s+add,\s+(\d+)\s+to\s+change,\s+(\d+)\s+to\s+destroy",
    re.IGNORECASE,
)
_NO_CHANGES_RE = re.compile(r"No changes\.|infrastructure (matches|is up-to-date)", re.IGNORECASE)


def _resolve_root(settings: Settings, override: str | None) -> Path:
    if override:
        return normalize_path(override, "path")
    if settings.terraform_root:
        return settings.terraform_root
    raise ValueError(
        "path não informado e INFRA_TERRAFORM_ROOT não definido. "
        "Passe `path` no payload da tool ou configure o env."
    )


def _build_error_payload(tool: str, exc: Exception) -> dict:
    """Erros tipados → payload JSON estruturado."""
    if isinstance(exc, BinaryNotFound):
        return {"error": "binary_not_found", "details": str(exc), "tool": tool}
    if isinstance(exc, CommandTimeout):
        return {"error": "timeout", "details": str(exc), "tool": tool}
    if isinstance(exc, ValueError):
        return {"error": "validation_error", "details": str(exc), "tool": tool}
    return {"error": "internal_error", "details": str(exc), "tool": tool}


# ---------------------------------------------------------------------- #
# terraform validate                                                      #
# ---------------------------------------------------------------------- #
def terraform_validate(settings: Settings, path: str | None = None) -> dict:
    """Roda `terraform validate -json` no diretório informado."""
    try:
        root = _resolve_root(settings, path)
    except ValueError as e:
        return _build_error_payload("terraform_validate", e)

    try:
        result = run_command(
            [settings.terraform_bin, "validate", "-json", "-no-color"],
            cwd=root,
            timeout=settings.validate_timeout,
            output_max_chars=settings.output_max_chars,
        )
    except (BinaryNotFound, CommandTimeout) as e:
        return _build_error_payload("terraform_validate", e)

    parsed: dict = {}
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Sem JSON → terraform pode não estar inicializado. Devolver raw.
        return {
            "valid": False,
            "diagnostics": [],
            "raw_stdout": result.stdout,
            "raw_stderr": result.stderr,
            "command": {
                "cmd": "terraform validate",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated,
            },
            "notes": [
                "Output não-JSON — verifique se o módulo está inicializado (`terraform init`)."
            ],
        }

    return {
        "valid": parsed.get("valid", False),
        "error_count": parsed.get("error_count", 0),
        "warning_count": parsed.get("warning_count", 0),
        "diagnostics": parsed.get("diagnostics", []),
        "command": {
            "cmd": "terraform validate",
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
        },
    }


# ---------------------------------------------------------------------- #
# terraform fmt -check                                                    #
# ---------------------------------------------------------------------- #
def terraform_fmt_check(
    settings: Settings,
    path: str | None = None,
    recursive: bool = True,
) -> dict:
    """Roda `terraform fmt -check -diff`. Não modifica arquivos."""
    try:
        root = _resolve_root(settings, path)
    except ValueError as e:
        return _build_error_payload("terraform_fmt_check", e)

    cmd = [settings.terraform_bin, "fmt", "-check", "-diff", "-no-color"]
    if recursive:
        cmd.append("-recursive")

    try:
        result = run_command(
            cmd,
            cwd=root,
            timeout=settings.validate_timeout,
            output_max_chars=settings.output_max_chars,
        )
    except (BinaryNotFound, CommandTimeout) as e:
        return _build_error_payload("terraform_fmt_check", e)

    # Exit code 3 = diferenças encontradas (não-fatal). 0 = OK. Outros = erro.
    files_to_format = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith(("@", "+", "-", " "))
    ]

    return {
        "is_formatted": result.exit_code == 0,
        "files_needing_format": files_to_format,
        "diff": result.stdout if result.exit_code != 0 else "",
        "command": {
            "cmd": "terraform fmt -check",
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
        },
    }


# ---------------------------------------------------------------------- #
# terraform plan                                                          #
# ---------------------------------------------------------------------- #
def terraform_plan(
    settings: Settings,
    path: str | None = None,
    out_file: str | None = None,
    var_file: str | None = None,
) -> dict:
    """Roda `terraform plan -no-color -out=<file> -detailed-exitcode`.

    Exit codes:
    - 0: sem mudanças
    - 1: erro
    - 2: sucesso com mudanças (plan aplicável)

    O `out_file` (default: `<root>/.infra-mcp.tfplan`) é input para
    `terraform_show_plan` e `cost_estimate_infracost`.
    """
    try:
        root = _resolve_root(settings, path)
    except ValueError as e:
        return _build_error_payload("terraform_plan", e)

    plan_file = Path(out_file) if out_file else (root / ".infra-mcp.tfplan")
    cmd = [
        settings.terraform_bin,
        "plan",
        "-no-color",
        "-input=false",
        "-detailed-exitcode",
        f"-out={plan_file}",
    ]
    if var_file:
        cmd.append(f"-var-file={var_file}")

    try:
        result = run_command(
            cmd,
            cwd=root,
            timeout=settings.plan_timeout,
            output_max_chars=settings.output_max_chars,
        )
    except (BinaryNotFound, CommandTimeout) as e:
        return _build_error_payload("terraform_plan", e)

    if result.exit_code == 1:
        return {
            "error": "plan_failed",
            "details": "terraform plan retornou erro (exit code 1)",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": {
                "cmd": "terraform plan",
                "exit_code": 1,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated,
            },
        }

    has_changes = result.exit_code == 2
    add = change = destroy = 0
    match = _PLAN_SUMMARY_RE.search(result.stdout)
    if match:
        add, change, destroy = (int(g) for g in match.groups())

    return {
        "has_changes": has_changes,
        "add": add,
        "change": change,
        "destroy": destroy,
        "plan_path": str(plan_file) if has_changes else None,
        "no_changes_reason": (
            None
            if has_changes
            else (_NO_CHANGES_RE.search(result.stdout).group(0) if _NO_CHANGES_RE.search(result.stdout) else "no changes")
        ),
        "stdout_excerpt": result.stdout[-2000:] if result.stdout else "",
        "command": {
            "cmd": "terraform plan",
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
        },
    }


# ---------------------------------------------------------------------- #
# terraform show -json <plan>                                             #
# ---------------------------------------------------------------------- #
def terraform_show_plan(
    settings: Settings,
    plan_path: str,
    path: str | None = None,
) -> dict:
    """Devolve o plan em JSON estruturado para análise programática."""
    try:
        root = _resolve_root(settings, path)
    except ValueError as e:
        return _build_error_payload("terraform_show_plan", e)

    try:
        plan_file = normalize_path(plan_path, "plan_path")
    except ValueError as e:
        return _build_error_payload("terraform_show_plan", e)

    if not plan_file.exists():
        return {
            "error": "plan_not_found",
            "details": f"Arquivo {plan_file} não existe",
            "tool": "terraform_show_plan",
        }

    try:
        result = run_command(
            [settings.terraform_bin, "show", "-json", str(plan_file)],
            cwd=root,
            timeout=settings.validate_timeout,
            output_max_chars=settings.output_max_chars,
        )
    except (BinaryNotFound, CommandTimeout) as e:
        return _build_error_payload("terraform_show_plan", e)

    if result.exit_code != 0:
        return {
            "error": "show_failed",
            "details": result.stderr or result.stdout,
            "command": {
                "cmd": "terraform show -json",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated,
            },
        }

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {
            "error": "invalid_json",
            "details": str(e),
            "tool": "terraform_show_plan",
        }

    changes = parsed.get("resource_changes", [])
    return {
        "format_version": parsed.get("format_version"),
        "terraform_version": parsed.get("terraform_version"),
        "resource_changes_count": len(changes),
        "changes_by_action": _group_by_action(changes),
        "changed_resources": [
            {
                "address": c.get("address"),
                "type": c.get("type"),
                "actions": (c.get("change") or {}).get("actions", []),
            }
            for c in changes[:50]  # limite defensivo
        ],
        "command": {
            "cmd": "terraform show -json",
            "exit_code": 0,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
        },
    }


def _group_by_action(changes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in changes:
        for action in (c.get("change") or {}).get("actions", []):
            counts[action] = counts.get(action, 0) + 1
    return counts
