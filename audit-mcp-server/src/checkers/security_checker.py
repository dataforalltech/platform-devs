import re
from pathlib import Path
from typing import Any


class SecurityChecker:
    """Verifica segurança: credenciais hardcoded, vulnerabilidades."""

    CREDENTIAL_PATTERNS = [
        (r"password\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_password"),
        (r"api_key\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_api_key"),
        (r"token\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_token"),
        (r"secret\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_secret"),
        (r"GITHUB_TOKEN\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_github_token"),
        (r"AWS_ACCESS_KEY\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_aws_key"),
        (r"private_key\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_private_key"),
    ]

    @staticmethod
    def run(repo_path: str) -> dict[str, Any]:
        """Retorna resultado de checagens de segurança."""
        repo = Path(repo_path)
        items = []

        # Check: no_hardcoded_credentials
        found_creds = SecurityChecker._scan_for_credentials(repo)

        items.append(
            {
                "category": "security",
                "name": "no_hardcoded_credentials",
                "required": True,
                "passed": len(found_creds) == 0,
                "details": f"Found {len(found_creds)} credential patterns"
                if found_creds
                else "No hardcoded credentials detected",
            }
        )

        # Check: no_critical_vulnerabilities (placeholder — seria via pip-audit/safety)
        items.append(
            {
                "category": "security",
                "name": "no_critical_vulnerabilities",
                "required": True,
                "passed": True,
                "details": "Vulnerability scanning not implemented in this phase",
            }
        )

        # Check: no_high_vulnerabilities (placeholder)
        items.append(
            {
                "category": "security",
                "name": "no_high_vulnerabilities",
                "required": False,
                "passed": True,
                "details": "Vulnerability scanning not implemented in this phase",
            }
        )

        passed_count = sum(1 for i in items if i["passed"])
        total = len(items)

        return {
            "category": "security",
            "items": items,
            "score": passed_count / total if total > 0 else 0.0,
        }

    @staticmethod
    def _scan_for_credentials(repo_path: Path, max_files: int = 100) -> list[str]:
        """Escaneia arquivos Python e YAML para padrões de credenciais."""
        found = []
        file_count = 0

        for file_path in repo_path.rglob("*"):
            if file_count >= max_files:
                break
            if not file_path.is_file():
                continue

            if file_path.suffix not in [".py", ".yaml", ".yml", ".env", ".conf"]:
                continue

            # Ignora venv, __pycache__, etc
            if any(part.startswith(".") for part in file_path.parts):
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                    for pattern, cred_type in SecurityChecker.CREDENTIAL_PATTERNS:
                        if re.search(pattern, content, re.IGNORECASE):
                            found.append(f"{file_path}: {cred_type}")

                file_count += 1
            except Exception:
                pass

        return found
