"""Testes adicionais de tenant_tool."""

from __future__ import annotations

from src.tools.tenant_tool import (
    _get_twin_tenant_id,
    get_tenant_config,
    set_tenant_config,
)


class TestGetTenantConfigFilters:
    def test_key_pattern_filter(self, store):
        set_tenant_config(store, "t1", "DATABASE_URL", "postgres://x")
        set_tenant_config(store, "t1", "REDIS_URL", "redis://x")
        result = get_tenant_config(store, "t1", key_pattern="database")
        assert result["found"] is True
        assert result["config"] == {"DATABASE_URL": "postgres://x"}

    def test_limit_truncates(self, store):
        for i in range(5):
            set_tenant_config(store, "t1", f"K{i}", str(i))
        result = get_tenant_config(store, "t1", limit=2)
        assert result["count"] == 2


class TestGetTwinTenantId:
    def test_returns_none_when_shared_module_absent(self, monkeypatch):
        """Sem o módulo shared.twin_client instalado, resolve para None (sem crash)."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("shared"):
                raise ImportError("no shared module")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert _get_twin_tenant_id() is None
