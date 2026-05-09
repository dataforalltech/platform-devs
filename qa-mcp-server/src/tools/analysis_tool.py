from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


def _detect_project_type(repo_path: str) -> str:
    p = Path(repo_path)
    if (p / "package.json").exists():
        return "javascript"
    return "python"


def _run_subprocess(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 120,
) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )
    return result.returncode, result.stdout, result.stderr


def run_linter(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    framework: str = "auto",
    fix: bool = False,
) -> dict:
    """
    Python: ruff check; JS/TS: npx eslint.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "run_linter",
        }

    actual_fw = framework if framework != "auto" else _detect_project_type(repo_path)

    if actual_fw in ("javascript", "typescript"):
        cmd = ["npx", "eslint", repo_path, "--format", "json"]
        tool_name = "eslint"
    else:
        cmd = ["ruff", "check", repo_path, "--output-format", "json"]
        if fix:
            cmd.append("--fix")
        tool_name = "ruff"

    try:
        rc, stdout, stderr = _run_subprocess(
            cmd, cwd=repo_path, timeout=settings.subprocess_timeout
        )
    except FileNotFoundError as exc:
        hint = "pip install ruff" if tool_name == "ruff" else "npm install eslint"
        return {
            "error": "tool_not_found",
            "tool": tool_name,
            "hint": hint,
            "details": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "details": f"Linter exceeded {settings.subprocess_timeout}s",
            "tool": "run_linter",
        }

    issues: list[dict] = []
    errors = 0
    warnings = 0
    files_checked = 0
    fixed = 0

    if tool_name == "ruff":
        try:
            data = json.loads(stdout) if stdout.strip() else []
            for item in data:
                sev = item.get("message", "")
                code = item.get("code", "")
                is_warning = code.startswith("W")
                if is_warning:
                    warnings += 1
                else:
                    errors += 1
                issues.append(
                    {
                        "file": item.get("filename", ""),
                        "line": item.get("location", {}).get("row", 0),
                        "col": item.get("location", {}).get("column", 0),
                        "code": code,
                        "message": sev,
                    }
                )
            # count fixed from stderr
            if fix and "Fixed" in stderr:
                m = re.search(r"Fixed (\d+)", stderr)
                fixed = int(m.group(1)) if m else 0
        except (json.JSONDecodeError, KeyError):
            pass

        # count files checked from output
        p = Path(repo_path)
        files_checked = len(list(p.rglob("*.py")))

    else:
        try:
            data = json.loads(stdout) if stdout.strip() else []
            for file_result in data:
                fname = file_result.get("filePath", "")
                msgs: list[dict] = file_result.get("messages") or []
                if msgs:
                    files_checked += 1
                for msg in msgs:
                    sev = msg.get("severity", 1)
                    if sev >= 2:
                        errors += 1
                    else:
                        warnings += 1
                    issues.append(
                        {
                            "file": fname,
                            "line": msg.get("line", 0),
                            "col": msg.get("column", 0),
                            "code": msg.get("ruleId", ""),
                            "message": msg.get("message", ""),
                        }
                    )
        except (json.JSONDecodeError, KeyError):
            pass

    run_id = store.save_run(
        run_type="linter",
        status="passed" if errors == 0 else "failed",
        summary={"errors": errors, "warnings": warnings},
        details={"issues": issues[:20]},
        repo_path=repo_path,
        framework=actual_fw,
    )

    ret: dict[str, Any] = {
        "framework": actual_fw,
        "tool": tool_name,
        "errors": errors,
        "warnings": warnings,
        "files_checked": files_checked,
        "issues": issues,
        "run_id": run_id,
    }
    if fix:
        ret["fixed"] = fixed
    return ret


def run_security_scan(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    framework: str = "auto",
) -> dict:
    """Python: bandit; JS/TS: npm audit."""
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "run_security_scan",
        }

    actual_fw = framework if framework != "auto" else _detect_project_type(repo_path)

    if actual_fw in ("javascript", "typescript"):
        cmd = ["npm", "audit", "--json"]
        tool_name = "npm_audit"
    else:
        cmd = ["bandit", "-r", repo_path, "-f", "json"]
        tool_name = "bandit"

    try:
        rc, stdout, stderr = _run_subprocess(
            cmd, cwd=repo_path, timeout=settings.subprocess_timeout
        )
    except FileNotFoundError as exc:
        hint = "pip install bandit" if tool_name == "bandit" else "npm install"
        return {
            "error": "tool_not_found",
            "tool": tool_name,
            "hint": hint,
            "details": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "details": f"Security scan exceeded {settings.subprocess_timeout}s",
            "tool": "run_security_scan",
        }

    findings: list[dict] = []
    high = medium = low = 0

    if tool_name == "bandit":
        try:
            data = json.loads(stdout) if stdout.strip() else {}
            results_list: list[dict] = data.get("results") or []
            for item in results_list:
                sev = item.get("issue_severity", "LOW").upper()
                if sev == "HIGH":
                    high += 1
                elif sev == "MEDIUM":
                    medium += 1
                else:
                    low += 1
                findings.append(
                    {
                        "severity": sev,
                        "confidence": item.get("issue_confidence", ""),
                        "file": item.get("filename", ""),
                        "line": item.get("line_number", 0),
                        "code": item.get("test_id", ""),
                        "message": item.get("issue_text", ""),
                    }
                )
        except (json.JSONDecodeError, KeyError):
            pass
    else:
        try:
            data = json.loads(stdout) if stdout.strip() else {}
            vulns: dict = data.get("vulnerabilities") or {}
            for pkg_name, info in vulns.items():
                sev = info.get("severity", "low").upper()
                if sev in ("CRITICAL", "HIGH"):
                    high += 1
                elif sev == "MODERATE":
                    medium += 1
                else:
                    low += 1
                findings.append(
                    {
                        "severity": sev,
                        "confidence": "HIGH",
                        "file": pkg_name,
                        "line": 0,
                        "code": info.get("name", ""),
                        "message": info.get("title", ""),
                    }
                )
        except (json.JSONDecodeError, KeyError):
            pass

    total_issues = high + medium + low
    run_id = store.save_run(
        run_type="security",
        status="passed" if high == 0 else "failed",
        summary={"high": high, "medium": medium, "low": low, "total_issues": total_issues},
        details={"findings": findings[:20]},
        repo_path=repo_path,
        framework=actual_fw,
    )

    return {
        "framework": actual_fw,
        "tool": tool_name,
        "high": high,
        "medium": medium,
        "low": low,
        "total_issues": total_issues,
        "findings": findings,
        "run_id": run_id,
    }


def check_dependencies(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
) -> dict:
    """pip-audit / safety para Python; npm audit para Node."""
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "check_dependencies",
        }

    p = Path(repo_path)
    is_node = (p / "package.json").exists()

    if is_node:
        cmd = ["npm", "audit", "--json"]
        tool_name = "npm_audit"
        fw = "javascript"
    else:
        cmd = ["pip-audit", "--format", "json", "--path", repo_path]
        tool_name = "pip-audit"
        fw = "python"

    try:
        rc, stdout, stderr = _run_subprocess(
            cmd, cwd=repo_path, timeout=settings.subprocess_timeout
        )
    except FileNotFoundError:
        if tool_name == "pip-audit":
            # fallback to safety
            try:
                cmd2 = ["safety", "check", "--json"]
                rc, stdout, stderr = _run_subprocess(
                    cmd2, cwd=repo_path, timeout=settings.subprocess_timeout
                )
                tool_name = "safety"
            except FileNotFoundError as exc2:
                return {
                    "error": "tool_not_found",
                    "tool": "pip-audit",
                    "hint": "pip install pip-audit",
                    "details": str(exc2),
                }
        else:
            return {
                "error": "tool_not_found",
                "tool": tool_name,
                "hint": "npm install",
                "details": "npm not found",
            }
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "details": f"Dependency check exceeded {settings.subprocess_timeout}s",
            "tool": "check_dependencies",
        }

    findings: list[dict] = []
    total_packages = 0

    if tool_name == "pip-audit":
        try:
            data = json.loads(stdout) if stdout.strip() else {}
            deps: list[dict] = data.get("dependencies") or []
            total_packages = len(deps)
            for dep in deps:
                for vuln in dep.get("vulns") or []:
                    findings.append(
                        {
                            "package": dep.get("name", ""),
                            "version": dep.get("version", ""),
                            "vuln_id": vuln.get("id", ""),
                            "description": vuln.get("description", ""),
                            "fix_version": (
                                vuln.get("fix_versions") or ["unknown"]
                            )[0],
                        }
                    )
        except (json.JSONDecodeError, KeyError):
            pass
    elif tool_name == "safety":
        try:
            data = json.loads(stdout) if stdout.strip() else []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, list) and len(item) >= 5:
                        findings.append(
                            {
                                "package": item[0],
                                "version": item[2],
                                "vuln_id": item[4] if len(item) > 4 else "",
                                "description": item[3] if len(item) > 3 else "",
                                "fix_version": "unknown",
                            }
                        )
        except (json.JSONDecodeError, IndexError):
            pass
    else:
        try:
            data = json.loads(stdout) if stdout.strip() else {}
            vulns: dict = data.get("vulnerabilities") or {}
            for pkg_name, info in vulns.items():
                findings.append(
                    {
                        "package": pkg_name,
                        "version": info.get("range", "unknown"),
                        "vuln_id": info.get("name", ""),
                        "description": info.get("title", ""),
                        "fix_version": info.get("fixAvailable", {}).get("version", "unknown")
                        if isinstance(info.get("fixAvailable"), dict)
                        else "unknown",
                    }
                )
        except (json.JSONDecodeError, KeyError):
            pass

    run_id = store.save_run(
        run_type="dependencies",
        status="passed" if not findings else "failed",
        summary={"total_packages": total_packages, "vulnerabilities": len(findings)},
        details={"findings": findings[:20]},
        repo_path=repo_path,
        framework=fw,
    )

    return {
        "framework": fw,
        "tool": tool_name,
        "total_packages": total_packages,
        "vulnerabilities": len(findings),
        "findings": findings,
        "run_id": run_id,
    }


def run_type_check(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    framework: str = "auto",
) -> dict:
    """mypy para Python; tsc para TypeScript."""
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "run_type_check",
        }

    actual_fw = framework if framework != "auto" else _detect_project_type(repo_path)

    if actual_fw in ("javascript", "typescript"):
        cmd = ["npx", "tsc", "--noEmit"]
        tool_name = "tsc"
    else:
        cmd = ["python", "-m", "mypy", repo_path, "--no-error-summary"]
        tool_name = "mypy"

    try:
        rc, stdout, stderr = _run_subprocess(
            cmd, cwd=repo_path, timeout=settings.subprocess_timeout
        )
    except FileNotFoundError as exc:
        hint = "pip install mypy" if tool_name == "mypy" else "npm install typescript"
        return {
            "error": "tool_not_found",
            "tool": tool_name,
            "hint": hint,
            "details": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "details": f"Type check exceeded {settings.subprocess_timeout}s",
            "tool": "run_type_check",
        }

    issues: list[dict] = []
    errors = 0
    warnings = 0
    files_checked = 0

    combined_output = (stdout + "\n" + stderr).strip()

    if tool_name == "mypy":
        # Parse mypy output: filename:line: error: message
        pattern = re.compile(r"^(.+?):(\d+):\s+(error|warning|note):\s+(.+)$", re.MULTILINE)
        seen_files: set[str] = set()
        for m in pattern.finditer(combined_output):
            fname, line, sev, msg = m.group(1), m.group(2), m.group(3), m.group(4)
            seen_files.add(fname)
            if sev == "error":
                errors += 1
            elif sev == "warning":
                warnings += 1
            issues.append(
                {
                    "file": fname,
                    "line": int(line),
                    "severity": sev,
                    "message": msg,
                }
            )
        files_checked = len(seen_files)
    else:
        # tsc: filename(line,col): error TSxxxx: message
        pattern = re.compile(
            r"^(.+?)\((\d+),\d+\):\s+(error|warning)\s+\w+:\s+(.+)$", re.MULTILINE
        )
        seen_files = set()
        for m in pattern.finditer(combined_output):
            fname, line, sev, msg = m.group(1), m.group(2), m.group(3), m.group(4)
            seen_files.add(fname)
            if sev == "error":
                errors += 1
            else:
                warnings += 1
            issues.append(
                {
                    "file": fname,
                    "line": int(line),
                    "severity": sev,
                    "message": msg,
                }
            )
        files_checked = len(seen_files)

    run_id = store.save_run(
        run_type="type_check",
        status="passed" if errors == 0 else "failed",
        summary={"errors": errors, "warnings": warnings},
        details={"issues": issues[:20]},
        repo_path=repo_path,
        framework=actual_fw,
    )

    return {
        "framework": actual_fw,
        "tool": tool_name,
        "errors": errors,
        "warnings": warnings,
        "files_checked": files_checked,
        "issues": issues,
        "run_id": run_id,
    }


def analyze_complexity(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    threshold: int | None = None,
) -> dict:
    """radon cc para Python; grep simples para JS/TS."""
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "analyze_complexity",
        }

    actual_threshold = threshold if threshold is not None else settings.complexity_threshold
    actual_fw = _detect_project_type(repo_path)

    hotspots: list[dict] = []
    total_functions = 0
    above_threshold = 0
    complexities: list[float] = []
    tool_name = "radon"

    if actual_fw in ("javascript", "typescript"):
        tool_name = "grep_count"
        p = Path(repo_path)
        extensions = ["*.js", "*.ts", "*.jsx", "*.tsx"]
        files = []
        for ext in extensions:
            files.extend(p.rglob(ext))

        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            keywords = ["if", "else", "for", "while", "switch", "catch", "&&", "||", "?"]
            cc = 1 + sum(len(re.findall(rf"\b{kw}\b", text)) for kw in keywords[:6])
            cc += text.count("&&") + text.count("||") + text.count("?")
            total_functions += 1
            complexities.append(float(cc))
            if cc > actual_threshold:
                above_threshold += 1
                hotspots.append(
                    {
                        "file": str(fpath),
                        "function": fpath.name,
                        "complexity": cc,
                        "rank": "C" if cc <= 20 else "D",
                    }
                )
    else:
        try:
            rc, stdout, stderr = _run_subprocess(
                ["radon", "cc", repo_path, "-j", "-s"],
                cwd=repo_path,
                timeout=settings.subprocess_timeout,
            )
        except FileNotFoundError as exc:
            return {
                "error": "tool_not_found",
                "tool": "radon",
                "hint": "pip install radon",
                "details": str(exc),
            }
        except subprocess.TimeoutExpired:
            return {
                "error": "timeout",
                "details": f"Complexity analysis exceeded {settings.subprocess_timeout}s",
                "tool": "analyze_complexity",
            }

        try:
            data: dict = json.loads(stdout) if stdout.strip() else {}
            for fpath, funcs in data.items():
                for func in funcs if isinstance(funcs, list) else []:
                    cc = func.get("complexity", 0)
                    rank = func.get("rank", "A")
                    total_functions += 1
                    complexities.append(float(cc))
                    if cc > actual_threshold:
                        above_threshold += 1
                        hotspots.append(
                            {
                                "file": fpath,
                                "function": func.get("name", ""),
                                "complexity": cc,
                                "rank": rank,
                            }
                        )
        except (json.JSONDecodeError, KeyError):
            pass

    avg_complexity = (
        round(sum(complexities) / len(complexities), 2) if complexities else 0.0
    )

    hotspots.sort(key=lambda h: h["complexity"], reverse=True)

    run_id = store.save_run(
        run_type="complexity",
        status="passed" if above_threshold == 0 else "warning",
        summary={
            "total_functions": total_functions,
            "above_threshold": above_threshold,
            "avg_complexity": avg_complexity,
        },
        details={"hotspots": hotspots[:10]},
        repo_path=repo_path,
    )

    return {
        "tool": tool_name,
        "threshold": actual_threshold,
        "total_functions": total_functions,
        "above_threshold": above_threshold,
        "avg_complexity": avg_complexity,
        "hotspots": hotspots,
        "run_id": run_id,
    }
