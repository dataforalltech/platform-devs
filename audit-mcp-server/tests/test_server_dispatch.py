import pytest

from src.server.mcp_server import _TOOL_SCHEMAS, _EXPECTED, _dispatch
from src.config.settings import AuditSettings
from src.db.store import AuditStore


def test_all_tools_registered():
    """Verifica que todos os tools estão registrados."""
    assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED


def test_tool_count():
    """Verifica contagem exata de tools."""
    assert len(_TOOL_SCHEMAS) == 9


def test_each_schema_has_description_and_schema():
    """Verifica que cada schema tem description e schema."""
    for name, meta in _TOOL_SCHEMAS.items():
        assert "description" in meta
        assert "schema" in meta
        assert meta["schema"]["type"] == "object"


def test_unknown_tool_raises_key_error(store, settings):
    """Verifica que tool desconhecido levanta erro."""
    with pytest.raises(KeyError):
        _dispatch("unknown_tool", {}, settings, store)


def test_dispatch_run_audit_missing_required_args(store, settings):
    """Testa run_audit sem args obrigatórios."""
    result = _dispatch("run_audit", {}, settings, store)
    assert "error" in result
