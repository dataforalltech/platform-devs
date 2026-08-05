"""Fixtures sem banco do domínio docs, portadas de `docs-mcp-server/tests/conftest.py`.

Só as `DocsSettings` puras que as tools compute-only precisam. As fixtures de MySQL
real ficaram de fora junto com os testes que as usam.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domains.docs.config.settings import DocsSettings


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Cria estrutura mínima de repo para testes.

    Cópia literal do conftest legado. O conteúdo importa: o validador cobra
    tamanho mínimo de seção no README e o formato Keep-a-Changelog no CHANGELOG,
    então uma versão "equivalente" escrita à mão reprova.
    """
    readme_content = (
        "# Test Service\n\n## Installation\n\nfoo bar baz qux quux\n\n## Usage\n\nbar baz qux quux corge\n"
    ) * 5
    (tmp_path / "README.md").write_text(readme_content, encoding="utf-8")
    changelog_content = (
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n- Initial release\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog_content, encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings() -> DocsSettings:
    """Settings puro (sem DB) para as tools compute-only."""
    return DocsSettings(
        stale_days_threshold=90,
        check_external_links=False,
        http_timeout=5.0,
        max_file_size_kb=500,
    )
