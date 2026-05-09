from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any


def _detect_framework(repo_path: str) -> str:
    """Detecta framework de teste: 'pytest' ou 'jest'."""
    p = Path(repo_path)
    if (p / "package.json").exists():
        pkg = (p / "package.json").read_text(encoding="utf-8", errors="ignore")
        if "jest" in pkg or "vitest" in pkg:
            return "jest"
    if (
        (p / "pyproject.toml").exists()
        or (p / "setup.py").exists()
        or (p / "requirements.txt").exists()
    ):
        return "pytest"
    # fallback
    return "pytest"


def _parse_pytest_output(output: str) -> dict[str, int]:
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", output)) else 0
    skipped = int(m.group(1)) if (m := re.search(r"(\d+) skipped", output)) else 0
    return {"passed": passed, "failed": failed, "errors": errors, "skipped": skipped}


def _parse_coverage_pct(output: str) -> float | None:
    m = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
    if m:
        return float(m.group(1))
    return None


def _parse_jest_output(output: str) -> dict[str, int]:
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"passed": passed, "failed": failed, "errors": 0, "skipped": 0}


def run_unit_tests(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    framework: str = "auto",
    test_path: str = ".",
    coverage: bool = False,
    timeout: int | None = None,
) -> dict:
    """Roda pytest ou jest no repo e retorna resultado estruturado."""
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "run_unit_tests",
        }

    p = Path(repo_path)
    if not p.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path does not exist: {repo_path}",
            "tool": "run_unit_tests",
        }

    actual_framework = framework if framework != "auto" else _detect_framework(repo_path)
    timeout_sec = timeout if timeout is not None else settings.subprocess_timeout

    if actual_framework == "jest":
        cmd = ["npx", "jest", "--passWithNoTests", "--ci"]
    else:
        cmd = ["python", "-m", "pytest", test_path, "--tb=short", "-q"]
        if coverage:
            cmd += [f"--cov={test_path}", "--cov-report=term-missing"]

    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=repo_path,
        )
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "details": f"Test run exceeded {timeout_sec}s",
            "tool": "run_unit_tests",
        }
    except FileNotFoundError as exc:
        return {
            "error": "tool_not_found",
            "tool": actual_framework,
            "hint": "pip install pytest" if actual_framework == "pytest" else "npm install jest",
            "details": str(exc),
        }

    duration_ms = int((time.monotonic() - start) * 1000)
    output = (result.stdout + "\n" + result.stderr)[:5000]

    if actual_framework == "jest":
        counts = _parse_jest_output(output)
    else:
        counts = _parse_pytest_output(output)

    status = "passed" if counts["failed"] == 0 and counts["errors"] == 0 else "failed"
    if result.returncode not in (0, 1):
        status = "error"

    ret: dict[str, Any] = {
        "framework": actual_framework,
        **counts,
        "duration_ms": duration_ms,
        "output": output,
        "status": status,
    }

    if coverage and actual_framework == "pytest":
        cov = _parse_coverage_pct(output)
        if cov is not None:
            ret["coverage_pct"] = cov

    run_id = store.save_run(
        run_type="unit",
        status=status,
        summary={k: counts[k] for k in ("passed", "failed", "errors", "skipped")},
        details={"output": output[:500]},
        repo_path=repo_path,
        framework=actual_framework,
        duration_ms=duration_ms,
    )
    ret["run_id"] = run_id
    return ret


def run_e2e_tests(
    store: Any,
    settings: Any,
    *,
    test_path: str,
    base_url: str,
    browser: str = "chromium",
    headless: bool = True,
    timeout: int | None = None,
) -> dict:
    """Roda testes Playwright (test_*.py ou *.spec.ts) em test_path."""
    if not base_url:
        return {
            "error": "ValidationError",
            "details": "base_url is required",
            "tool": "run_e2e_tests",
        }
    if not test_path:
        return {
            "error": "ValidationError",
            "details": "test_path is required",
            "tool": "run_e2e_tests",
        }

    timeout_sec = timeout if timeout is not None else settings.subprocess_timeout

    # Detecta tipo de teste pelo conteúdo do diretório
    p = Path(test_path)
    has_spec_ts = list(p.glob("**/*.spec.ts")) + list(p.glob("**/*.spec.js"))
    has_py = list(p.glob("**/test_*.py"))

    if has_spec_ts:
        cmd = ["npx", "playwright", "test", "--headed" if not headless else ""]
        cmd = [c for c in cmd if c]  # remove vazios
    elif has_py:
        cmd = [
            "python",
            "-m",
            "pytest",
            test_path,
            f"--base-url={base_url}",
            "-v",
            "--tb=short",
        ]
    else:
        # fallback: tenta npx playwright test
        cmd = ["npx", "playwright", "test"]

    env_extra: dict[str, str] = {"PLAYWRIGHT_BROWSER": browser}

    start = time.monotonic()
    try:
        import os

        env = {**os.environ, **env_extra}
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=test_path if p.is_dir() else str(p.parent),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "details": f"E2E test run exceeded {timeout_sec}s",
            "tool": "run_e2e_tests",
        }
    except FileNotFoundError as exc:
        return {
            "error": "tool_not_found",
            "tool": "playwright",
            "hint": "pip install playwright && playwright install",
            "details": str(exc),
        }

    duration_ms = int((time.monotonic() - start) * 1000)
    output = (result.stdout + "\n" + result.stderr)[:5000]

    counts = _parse_pytest_output(output)
    passed = counts["passed"]
    failed = counts["failed"] + counts["errors"]

    # fallback parse for playwright TS output
    if passed == 0 and failed == 0:
        if m := re.search(r"(\d+)\s+passed", output):
            passed = int(m.group(1))
        if m := re.search(r"(\d+)\s+failed", output):
            failed = int(m.group(1))

    status = "passed" if failed == 0 and result.returncode in (0, 1) else "failed"
    if result.returncode not in (0, 1):
        status = "error"

    run_id = store.save_run(
        run_type="e2e",
        status=status,
        summary={"passed": passed, "failed": failed},
        details={"output": output[:500], "base_url": base_url},
        framework="playwright",
        duration_ms=duration_ms,
    )

    return {
        "browser": browser,
        "base_url": base_url,
        "passed": passed,
        "failed": failed,
        "duration_ms": duration_ms,
        "output": output,
        "status": status,
        "run_id": run_id,
    }
