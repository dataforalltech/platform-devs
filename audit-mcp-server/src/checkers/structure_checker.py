from pathlib import Path
from typing import Any


class StructureChecker:
    """Verifica estrutura básica de diretórios e arquivos obrigatórios."""

    checks = {
        "has_src_dir": ("src/", True),
        "has_tests_dir": ("tests/", True),
        "has_pyproject_toml": ("pyproject.toml", False),
        "has_dockerfile": ("Dockerfile", False),
        "has_dockerfile_prod": ("Dockerfile.prod", False),
        "has_changelog": ("CHANGELOG.md", False),
    }

    @staticmethod
    def run(repo_path: str) -> dict[str, Any]:
        """Retorna resultado de checagens estruturais."""
        repo = Path(repo_path)
        items = []

        for check_name, (target, is_required) in StructureChecker.checks.items():
            target_path = repo / target
            passed = target_path.exists()

            items.append(
                {
                    "category": "structure",
                    "name": check_name,
                    "required": is_required,
                    "passed": passed,
                    "details": str(target_path) if passed else f"Not found: {target}",
                }
            )

        passed_count = sum(1 for i in items if i["passed"])
        total = len(items)

        return {
            "category": "structure",
            "items": items,
            "score": passed_count / total if total > 0 else 0.0,
        }
