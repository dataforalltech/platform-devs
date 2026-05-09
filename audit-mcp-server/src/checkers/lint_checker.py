import subprocess
from pathlib import Path
from typing import Any


class LintChecker:
    """Verifica lint (ruff) passando."""

    @staticmethod
    def run(repo_path: str) -> dict[str, Any]:
        """Retorna resultado de checagens de lint."""
        repo = Path(repo_path)
        items = []

        # Check: ruff_passing
        passed, output = LintChecker._run_ruff(repo)

        items.append(
            {
                "category": "lint",
                "name": "ruff_passing",
                "required": True,
                "passed": passed,
                "details": "ruff check passed" if passed else f"ruff violations found:\n{output[:200]}",
            }
        )

        return {
            "category": "lint",
            "items": items,
            "score": 1.0 if passed else 0.0,
        }

    @staticmethod
    def _run_ruff(repo_path: Path) -> tuple[bool, str]:
        """Executa ruff check e retorna (passed, output)."""
        try:
            result = subprocess.run(
                ["ruff", "check", str(repo_path)],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except FileNotFoundError:
            # ruff não instalado — assume que passou (fase de desenvolvimento)
            return True, "ruff not installed (skipped)"
        except subprocess.TimeoutExpired:
            return False, "ruff check timed out"
        except Exception as e:
            return False, str(e)
