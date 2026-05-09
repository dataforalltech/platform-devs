import pytest
import tempfile
from pathlib import Path

from src.config.settings import AuditSettings
from src.db.store import AuditStore


@pytest.fixture
def tmp_repo():
    """Cria repo temporário com estrutura básica."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "pyproject.toml").write_text("[project]\nname = 'test'")
        (repo / "README.md").write_text("# Test Repo")
        yield repo


@pytest.fixture
def store():
    """SQLite store em memória."""
    return AuditStore(db_path=":memory:")


@pytest.fixture
def settings(tmp_path):
    """Configurações para testes."""
    return AuditSettings(
        db_path=":memory:",
        github_token="test_token",
        policies_path=str(Path(__file__).parent.parent / "src" / "policies"),
    )
