import pytest

from src.checkers.structure_checker import StructureChecker
from src.checkers.test_checker import TestChecker
from src.checkers.security_checker import SecurityChecker
from src.checkers.docs_checker import DocsChecker


def test_structure_checker_has_src_dir(tmp_repo):
    """Testa detecção de src/."""
    result = StructureChecker.run(str(tmp_repo))
    assert result["category"] == "structure"
    found_has_src = any(i["name"] == "has_src_dir" and i["passed"] for i in result["items"])
    assert found_has_src


def test_structure_checker_has_pyproject(tmp_repo):
    """Testa detecção de pyproject.toml."""
    result = StructureChecker.run(str(tmp_repo))
    found = any(i["name"] == "has_pyproject_toml" and i["passed"] for i in result["items"])
    assert found


def test_test_checker_has_tests(tmp_repo):
    """Testa detecção de testes."""
    result = TestChecker.run(str(tmp_repo))
    assert result["category"] == "tests"
    found = any(i["name"] == "has_tests" for i in result["items"])
    assert found


def test_security_checker_no_hardcoded_credentials(tmp_repo):
    """Testa segurança — sem credenciais hardcoded."""
    result = SecurityChecker.run(str(tmp_repo))
    assert result["category"] == "security"
    found = any(i["name"] == "no_hardcoded_credentials" and i["passed"] for i in result["items"])
    assert found


def test_docs_checker_has_readme(tmp_repo):
    """Testa documentação — README presente."""
    result = DocsChecker.run(str(tmp_repo), env="dev")
    assert result["category"] == "docs"
    found = any(i["name"] == "has_readme" and i["passed"] for i in result["items"])
    assert found
