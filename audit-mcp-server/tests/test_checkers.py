import json
import subprocess

from src.checkers.docs_checker import DocsChecker
from src.checkers.lint_checker import LintChecker
from src.checkers.resolver import RepoResolver
from src.checkers.security_checker import SecurityChecker
from src.checkers.structure_checker import StructureChecker
from src.checkers.test_checker import TestChecker


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


# --------------------------------------------------------------------------- #
# StructureChecker — arquivo ausente
# --------------------------------------------------------------------------- #


def test_structure_checker_missing_dockerfile(tmp_repo):
    """Dockerfile ausente marca item como não passou."""
    result = StructureChecker.run(str(tmp_repo))
    item = next(i for i in result["items"] if i["name"] == "has_dockerfile")
    assert item["passed"] is False
    assert "Not found" in item["details"]


# --------------------------------------------------------------------------- #
# SecurityChecker — detecção de credenciais
# --------------------------------------------------------------------------- #


def test_security_checker_detects_hardcoded_credential(tmp_repo):
    """Credencial hardcoded é detectada e reprova o check."""
    (tmp_repo / "src" / "cfg.py").write_text('password = "supersecret123"\n', encoding="utf-8")
    result = SecurityChecker.run(str(tmp_repo))
    item = next(i for i in result["items"] if i["name"] == "no_hardcoded_credentials")
    assert item["passed"] is False


def test_security_checker_skips_dotfiles(tmp_repo):
    """Arquivos em diretórios ocultos são ignorados pelo scan."""
    hidden = tmp_repo / ".venv"
    hidden.mkdir()
    (hidden / "leak.py").write_text('api_key = "leak"\n', encoding="utf-8")
    result = SecurityChecker.run(str(tmp_repo))
    item = next(i for i in result["items"] if i["name"] == "no_hardcoded_credentials")
    assert item["passed"] is True


# --------------------------------------------------------------------------- #
# DocsChecker — variáveis de ambiente e prod
# --------------------------------------------------------------------------- #


def test_docs_checker_env_vars_via_readme(tmp_repo):
    """README mencionando 'environment' documenta env vars."""
    (tmp_repo / "README.md").write_text("# Repo\nEnvironment variables here", encoding="utf-8")
    result = DocsChecker.run(str(tmp_repo), env="hml")
    item = next(i for i in result["items"] if i["name"] == "has_env_vars_documented")
    assert item["passed"] is True


def test_docs_checker_env_vars_via_env_example(tmp_repo):
    """`.env.example` documenta env vars quando não há README (fallback)."""
    # O README tem precedência: se existe mas não menciona env, retorna False.
    # O fallback para .env.example só é avaliado sem README.
    (tmp_repo / "README.md").unlink()
    (tmp_repo / ".env.example").write_text("FOO=bar", encoding="utf-8")
    assert DocsChecker._check_env_documentation(tmp_repo) is True


def test_docs_checker_env_vars_absent(tmp_repo):
    """Sem README relevante nem .env.example, env vars não documentadas."""
    (tmp_repo / "README.md").write_text("# Repo", encoding="utf-8")
    assert DocsChecker._check_env_documentation(tmp_repo) is False


def test_docs_checker_prod_requires_runbook(tmp_repo):
    """Em prod, runbook/rollback ausentes ficam marcados como obrigatórios."""
    result = DocsChecker.run(str(tmp_repo), env="prod")
    runbook = next(i for i in result["items"] if i["name"] == "has_runbook")
    assert runbook["required"] is True
    assert runbook["passed"] is False


# --------------------------------------------------------------------------- #
# TestChecker — leitura de coverage.json
# --------------------------------------------------------------------------- #


def test_test_checker_reads_coverage_json(tmp_repo):
    """coverage.json é lido e reflete nos checks de cobertura."""
    (tmp_repo / "coverage.json").write_text(
        json.dumps({"totals": {"percent_covered": 85.0}}), encoding="utf-8"
    )
    result = TestChecker.run(str(tmp_repo))
    assert result["coverage_pct"] == 85
    cov80 = next(i for i in result["items"] if i["name"] == "min_coverage_80")
    assert cov80["passed"] is True
    cov90 = next(i for i in result["items"] if i["name"] == "min_coverage_90")
    assert cov90["passed"] is False


def test_test_checker_no_coverage_file(tmp_repo):
    """Sem coverage.json, cobertura é 0."""
    result = TestChecker.run(str(tmp_repo))
    assert result["coverage_pct"] == 0


def test_test_checker_corrupt_coverage_json(tmp_repo):
    """coverage.json inválido é tolerado (retorna 0)."""
    (tmp_repo / "coverage.json").write_text("{not json", encoding="utf-8")
    result = TestChecker.run(str(tmp_repo))
    assert result["coverage_pct"] == 0


# --------------------------------------------------------------------------- #
# LintChecker — mocka subprocess (hermético)
# --------------------------------------------------------------------------- #


def test_lint_checker_passing(tmp_repo, monkeypatch):
    """ruff retornando 0 marca ruff_passing como passou."""

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    result = LintChecker.run(str(tmp_repo))
    assert result["score"] == 1.0
    assert result["items"][0]["passed"] is True


def test_lint_checker_failing(tmp_repo, monkeypatch):
    """ruff retornando != 0 reprova e inclui o output."""

    class _Result:
        returncode = 1
        stdout = "E501 line too long"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    result = LintChecker.run(str(tmp_repo))
    assert result["score"] == 0.0
    assert "E501" in result["items"][0]["details"]


def test_lint_checker_ruff_not_installed(tmp_repo, monkeypatch):
    """ruff ausente (FileNotFoundError) é tratado como passou."""

    def raise_fnf(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    passed, output = LintChecker._run_ruff(tmp_repo)
    assert passed is True
    assert "not installed" in output


def test_lint_checker_timeout(tmp_repo, monkeypatch):
    """Timeout do ruff reprova o check."""

    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ruff", timeout=30)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    passed, output = LintChecker._run_ruff(tmp_repo)
    assert passed is False
    assert "timed out" in output


def test_lint_checker_generic_exception(tmp_repo, monkeypatch):
    """Exceção genérica reprova e devolve a mensagem."""

    def raise_err(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(subprocess, "run", raise_err)
    passed, output = LintChecker._run_ruff(tmp_repo)
    assert passed is False
    assert "nope" in output


# --------------------------------------------------------------------------- #
# RepoResolver
# --------------------------------------------------------------------------- #


def test_resolver_with_existing_repo_path(tmp_repo):
    """repo_path existente é retornado como está."""
    resolver = RepoResolver()
    assert resolver.resolve("r", repo_path=str(tmp_repo), env="dev") == str(tmp_repo)


def test_resolver_with_missing_repo_path():
    """repo_path inexistente retorna None."""
    resolver = RepoResolver()
    assert resolver.resolve("r", repo_path="/does/not/exist", env="dev") is None


def test_resolver_dev_via_env_root(tmp_path, monkeypatch):
    """Em dev, resolve procura o repo sob AUDIT_REPOS_ROOT."""
    (tmp_path / "myrepo").mkdir()
    monkeypatch.setenv("AUDIT_REPOS_ROOT", str(tmp_path))
    resolver = RepoResolver()
    resolved = resolver.resolve("myrepo", env="dev")
    assert resolved == str(tmp_path / "myrepo")


def test_resolver_non_dev_returns_none(monkeypatch):
    """Sem repo_path e env != dev, resolve retorna None."""
    monkeypatch.delenv("AUDIT_REPOS_ROOT", raising=False)
    monkeypatch.delenv("REPOS_ROOT", raising=False)
    resolver = RepoResolver()
    assert resolver.resolve("r", env="prod") is None


def test_resolver_cleanup(tmp_path):
    """cleanup remove diretórios temporários registrados."""
    tmp_dir = tmp_path / "tmpclone"
    tmp_dir.mkdir()
    resolver = RepoResolver()
    resolver._temp_dirs["r"] = str(tmp_dir)
    resolver.cleanup()
    assert not tmp_dir.exists()
    assert resolver._temp_dirs == {}
