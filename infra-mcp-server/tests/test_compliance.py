"""Testes do padrão Tier-2 de compliance (STD-SEC-001/004/006, STD-OBS-001).

Cobre: RUNTIME_ENV + enforce_security_invariants (settings.py), Vault-fallback
load_secret (config/secrets.py) e o logging estruturado JSON (config/logging.py).
"""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from src.config.logging import JsonLogFormatter, configure_logging
from src.config.secrets import SERVICE, SecretResolutionError, load_secret
from src.config.settings import Settings


def _vault_duplo(monkeypatch, **valores: str) -> dict[str, str]:
    """Instala um Vault de mentira com a API REAL da lib (``service=`` / ``get()``).

    Necessário em qualquer teste que construa Settings com ``RUNTIME_ENV="cloud"``:
    ali o bootstrap resolve do Vault e NÃO aceita fallback de env (STD-SEC-002
    §MUST — falha fechada). Sem o dublê, a própria construção recusa.
    """
    visto: dict[str, str] = {}

    class _FakeVault:
        def __init__(self, service: str) -> None:
            visto["service"] = service

        def get(self, name: str, *, field: str = "value") -> str:
            visto["name"] = name
            return valores.get(name, "")

    monkeypatch.setitem(
        __import__("sys").modules,
        "platform_crypto",
        type("m", (), {"VaultSecretsClient": _FakeVault}),
    )
    return visto


# ── RUNTIME_ENV validator ─────────────────────────────────────────────────────
def test_runtime_env_default_local():
    assert Settings().runtime_env == "local"


def test_runtime_env_normalizes_case(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    assert Settings(RUNTIME_ENV="CLOUD").runtime_env == "cloud"


def test_runtime_env_rejects_unknown():
    with pytest.raises(ValidationError):
        Settings(RUNTIME_ENV="staging")


# ── enforce_security_invariants ───────────────────────────────────────────────
def test_enforce_ok_local_defaults():
    # local + docs off + audiência canônica → passa (retorna None)
    assert Settings(MCP_TWIN_AUDIENCE="mcp:infra-mcp").enforce_security_invariants() is None


def test_enforce_rejects_docs_enabled():
    s = Settings(DOCS_ENABLED=True)
    with pytest.raises(RuntimeError, match="STD-SEC-001"):
        s.enforce_security_invariants()


def test_enforce_rejects_bad_audience():
    s = Settings(MCP_TWIN_AUDIENCE="infra-mcp")
    with pytest.raises(RuntimeError, match="STD-SEC-006"):
        s.enforce_security_invariants()


def test_enforce_requires_jwks_in_cloud(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="pw")
    s = Settings(RUNTIME_ENV="cloud", MCP_TWIN_AUDIENCE="mcp:infra-mcp", URL_ADMIN_TWIN_JWKS="")
    with pytest.raises(RuntimeError, match="URL_ADMIN_TWIN_JWKS"):
        s.enforce_security_invariants()


def test_enforce_requires_admin_db_in_cloud(monkeypatch):
    # cloud + jwks mas SEM ADMIN_DB_HOST/PASSWORD → o allocator agora é tenant-scoped no
    # ORM (há credencial de DB de verdade), então o boot falha fechado (STD-SEC-004).
    # Em cloud a fonte da senha é o Vault, não o env: é ele que precisa não ter a chave.
    _vault_duplo(monkeypatch, db_password="pw")
    s = Settings(
        RUNTIME_ENV="cloud",
        MCP_TWIN_AUDIENCE="mcp:infra-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks",
    )
    with pytest.raises(RuntimeError, match="ADMIN_DB_HOST/ADMIN_DB_PASSWORD"):
        s.enforce_security_invariants()


def test_enforce_ok_in_cloud_with_jwks_and_admin_db(monkeypatch):
    _vault_duplo(monkeypatch, db_password="pw", admin_db_password="s3cr3t")
    s = Settings(
        RUNTIME_ENV="cloud",
        MCP_TWIN_AUDIENCE="mcp:infra-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks",
        ADMIN_DB_HOST="admin-db.local",
    )
    assert s.enforce_security_invariants() is None


# ── load_secret (bootstrap STD-SEC-004) ───────────────────────────────────────
def test_load_secret_env_fallback_when_no_vault(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("infra_lease_secret", env_fallback="from-env") == "from-env"


def test_load_secret_absent_returns_none(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    assert load_secret("infra_lease_secret") is None


def test_load_secret_degrades_when_vault_import_fails(monkeypatch):
    # VAULT_ADDR setado mas platform_crypto não instalado → ImportError capturado,
    # degrada para env. Isto continua valendo em LOCAL — e só nele.
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    assert load_secret("infra_lease_secret", env_fallback="env-val") == "env-val"


def test_load_secret_uses_vault_when_available(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    visto = _vault_duplo(monkeypatch, infra_lease_secret="vault-val")
    assert load_secret("infra_lease_secret", env_fallback="env-val") == "vault-val"
    # Regressão: o 1º argumento do cliente é o ESPAÇO do serviço, nunca a URL do
    # Vault — o bug original era `VaultSecretsClient(vault_addr).get_secret(key)`.
    assert visto["service"] == SERVICE
    assert "://" not in visto["service"]


# ── falha fechada em cloud (STD-SEC-002 §MUST) ────────────────────────────────
def test_load_secret_cloud_vault_indisponivel_recusa(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")

    class _Quebrado:
        def __init__(self, service: str) -> None:
            pass

        def get(self, name: str, *, field: str = "value") -> str:
            raise RuntimeError("vault down")

    monkeypatch.setitem(
        __import__("sys").modules,
        "platform_crypto",
        type("m", (), {"VaultSecretsClient": _Quebrado}),
    )
    with pytest.raises(SecretResolutionError):
        load_secret("infra_lease_secret", env_fallback="env-val", runtime_env="cloud")


def test_load_secret_cloud_ignora_fallback_de_env(monkeypatch):
    monkeypatch.setenv("VAULT_ADDR", "http://vault.local:8200")
    _vault_duplo(monkeypatch)
    assert (
        load_secret("infra_lease_secret", env_fallback="env-val", runtime_env="cloud")
        is None
    )


# ── JsonLogFormatter / configure_logging (STD-OBS-001) ────────────────────────
def _record(**kw) -> logging.LogRecord:
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    for k, v in kw.items():
        setattr(rec, k, v)
    return rec


def test_formatter_emits_service_and_extras():
    out = json.loads(JsonLogFormatter().format(_record(extras={"db_path": ":memory:"}, tenant_id="T")))
    assert out["service"] == "infra-mcp"
    assert out["msg"] == "hello"
    assert out["extras"] == {"db_path": ":memory:"}
    assert out["tenant_id"] == "T"


def test_formatter_serializes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "fail", None, sys.exc_info())
    out = json.loads(JsonLogFormatter().format(rec))
    assert out["exc_type"] == "ValueError"
    assert "boom" in out["exc"]


def test_configure_logging_installs_json_handler():
    root = logging.getLogger()
    original = root.handlers[:]
    original_level = root.level
    try:
        configure_logging(Settings(MCP_SERVICE_LOG_LEVEL="WARNING"))
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
        assert root.level == logging.WARNING
    finally:
        root.handlers[:] = original
        root.setLevel(original_level)
