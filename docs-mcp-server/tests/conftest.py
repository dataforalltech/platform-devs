from __future__ import annotations

import pytest

from src.config.settings import DocsSettings
from src.db.store import DocsStore


@pytest.fixture
def store():
    s = DocsStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def settings():
    return DocsSettings(
        db_path=":memory:",
        stale_days_threshold=90,
        check_external_links=False,
        http_timeout=5.0,
        max_file_size_kb=500,
    )


@pytest.fixture
def tmp_repo(tmp_path):
    """Cria estrutura mínima de repo para testes."""
    readme_content = (
        "# Test Service\n\n"
        "## Installation\n\nfoo bar baz qux quux\n\n"
        "## Usage\n\nbar baz qux quux corge\n"
    ) * 5
    (tmp_path / "README.md").write_text(readme_content, encoding="utf-8")
    changelog_content = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "## [1.0.0] - 2026-01-01\n\n"
        "### Added\n- Initial release\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog_content, encoding="utf-8")
    return tmp_path
