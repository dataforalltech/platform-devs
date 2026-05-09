import json
from pathlib import Path
from typing import Any


class TestChecker:
    """Verifica existência de testes e cobertura."""

    @staticmethod
    def run(repo_path: str) -> dict[str, Any]:
        """Retorna resultado de checagens de testes."""
        repo = Path(repo_path)
        items = []

        # Check: has_tests
        tests_dir = repo / "tests"
        has_tests = tests_dir.exists() and len(list(tests_dir.glob("test_*.py"))) > 0

        items.append(
            {
                "category": "tests",
                "name": "has_tests",
                "required": True,
                "passed": has_tests,
                "details": f"Found {len(list(tests_dir.glob('test_*.py')))} test files" if has_tests else "No test files found",
            }
        )

        # Check: coverage levels
        coverage_pct = TestChecker._read_coverage(repo)

        for min_pct in [60, 70, 80, 90]:
            check_name = f"min_coverage_{min_pct}"
            passed = coverage_pct >= min_pct

            items.append(
                {
                    "category": "tests",
                    "name": check_name,
                    "required": min_pct <= 70,
                    "passed": passed,
                    "details": f"Coverage: {coverage_pct}%",
                }
            )

        passed_count = sum(1 for i in items if i["passed"])
        total = len(items)

        return {
            "category": "tests",
            "items": items,
            "score": passed_count / total if total > 0 else 0.0,
            "coverage_pct": coverage_pct,
        }

    @staticmethod
    def _read_coverage(repo_path: Path) -> int:
        """Tenta ler cobertura de coverage.json ou coverage.xml."""
        # Tenta coverage.json (pytest-cov)
        coverage_json = repo_path / "coverage.json"
        if coverage_json.exists():
            try:
                with open(coverage_json) as f:
                    data = json.load(f)
                    if "totals" in data and "percent_covered" in data["totals"]:
                        return int(data["totals"]["percent_covered"])
            except Exception:
                pass

        # Se não encontrou, retorna 0
        return 0
