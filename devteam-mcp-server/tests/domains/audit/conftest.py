"""Fixtures sem banco do domínio audit, portadas de `audit-mcp-server/tests/conftest.py`.

Só o que os testes de checker/tool precisam. O conftest legado tem também as
fixtures de MySQL real e de RS256; elas ficaram de fora junto com os testes que as
usam — este repositório não tem executor de CI que suba o MySQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domains.audit.config.settings import AuditSettings


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Repositório temporário com a estrutura mínima que os checkers inspecionam."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'test'", encoding="utf-8")
    (repo / "README.md").write_text("# Test Repo", encoding="utf-8")
    return repo


@pytest.fixture
def settings() -> AuditSettings:
    """Settings herméticas — apontam para as policies reais do repositório."""
    return AuditSettings()
