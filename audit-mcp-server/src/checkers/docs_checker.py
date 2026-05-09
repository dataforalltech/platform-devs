from pathlib import Path
from typing import Any


class DocsChecker:
    """Verifica documentação obrigatória."""

    checks = {
        "has_readme": ("README.md", True),
        "has_changelog": ("CHANGELOG.md", False),
        "has_runbook": ("docs/runbook.md", True, "prod"),
        "has_rollback_plan": ("docs/rollback.md", True, "prod"),
        "has_adr": ("docs/decisions/", False),
    }

    @staticmethod
    def run(repo_path: str, env: str = "dev") -> dict[str, Any]:
        """Retorna resultado de checagens de documentação."""
        repo = Path(repo_path)
        items = []

        items.append(
            {
                "category": "docs",
                "name": "has_readme",
                "required": True,
                "passed": (repo / "README.md").exists(),
                "details": "README.md present" if (repo / "README.md").exists() else "README.md not found",
            }
        )

        items.append(
            {
                "category": "docs",
                "name": "has_changelog",
                "required": False,
                "passed": (repo / "CHANGELOG.md").exists(),
                "details": "CHANGELOG.md present"
                if (repo / "CHANGELOG.md").exists()
                else "CHANGELOG.md not found",
            }
        )

        # Runbook é obrigatório em PROD
        runbook_path = repo / "docs" / "runbook.md"
        is_required_for_prod = env == "prod"

        items.append(
            {
                "category": "docs",
                "name": "has_runbook",
                "required": is_required_for_prod,
                "passed": runbook_path.exists(),
                "details": f"Runbook present (required for {env})"
                if runbook_path.exists()
                else f"docs/runbook.md not found (required for {env})",
            }
        )

        # Rollback plan é obrigatório em PROD
        rollback_path = repo / "docs" / "rollback.md"
        is_required_for_prod = env == "prod"

        items.append(
            {
                "category": "docs",
                "name": "has_rollback_plan",
                "required": is_required_for_prod,
                "passed": rollback_path.exists(),
                "details": f"Rollback plan present (required for {env})"
                if rollback_path.exists()
                else f"docs/rollback.md not found (required for {env})",
            }
        )

        items.append(
            {
                "category": "docs",
                "name": "has_adr",
                "required": False,
                "passed": (repo / "docs" / "decisions").exists(),
                "details": "docs/decisions/ directory present"
                if (repo / "docs" / "decisions").exists()
                else "docs/decisions/ not found",
            }
        )

        # Check env vars documentation (requer leitura do README ou arquivo de config)
        has_env_docs = DocsChecker._check_env_documentation(repo)

        items.append(
            {
                "category": "docs",
                "name": "has_env_vars_documented",
                "required": env != "dev",
                "passed": has_env_docs,
                "details": "Environment variables documented" if has_env_docs else "Environment variables not documented",
            }
        )

        passed_count = sum(1 for i in items if i["passed"])
        total = len(items)

        return {
            "category": "docs",
            "items": items,
            "score": passed_count / total if total > 0 else 0.0,
        }

    @staticmethod
    def _check_env_documentation(repo_path: Path) -> bool:
        """Verifica se há documentação de variáveis de ambiente."""
        readme = repo_path / "README.md"
        if readme.exists():
            try:
                content = readme.read_text()
                return "environment" in content.lower() or "env_var" in content.lower()
            except Exception:
                pass

        # Verifica se existe arquivo de configuração de exemplo
        env_example = repo_path / ".env.example"
        if env_example.exists():
            return True

        return False
