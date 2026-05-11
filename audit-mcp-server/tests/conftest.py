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
def store(settings):
    """PostgreSQL store para testes."""
    store = AuditStore(settings=settings)
    yield store
    store.close()


@pytest.fixture
def settings(tmp_path):
    """Configurações para testes com PostgreSQL."""
    return AuditSettings(
        pg_host="claude-dev",
        pg_port=5432,
        pg_db="app",
        pg_user="postgres",
        pg_password="postgres_password_local_dev",
        pg_min_conn=1,
        pg_max_conn=5,
        github_token="test_token",
        policies_path=str(Path(__file__).parent.parent / "src" / "policies"),
    )
