"""Unidades herméticas (sem DB) das tools — resolução de tenant via dev-twin-mcp.

Cobre ``_get_twin_tenant_id`` nos dois ramos: import indisponível → None (degradação
graciosa) e cliente presente → tenant_id resolvido. Não toca o store nem o MySQL.
"""

from __future__ import annotations

import sys
import types

import src.tools.tenant_tool as tt


def test_get_twin_tenant_id_returns_none_when_unavailable(monkeypatch):
    # Sem o pacote shared.twin_client, o import falha → degradação graciosa (None).
    monkeypatch.setitem(sys.modules, "shared", types.ModuleType("shared"))
    monkeypatch.delitem(sys.modules, "shared.twin_client", raising=False)
    assert tt._get_twin_tenant_id() is None


def test_get_twin_tenant_id_resolves_from_client(monkeypatch):
    shared_pkg = types.ModuleType("shared")
    twin_mod = types.ModuleType("shared.twin_client")

    class _TwinClient:
        @classmethod
        def from_env(cls) -> _TwinClient:
            return cls()

        def get_tenant_id(self) -> str:
            return "tenant_from_twin"

    twin_mod.TwinClient = _TwinClient
    monkeypatch.setitem(sys.modules, "shared", shared_pkg)
    monkeypatch.setitem(sys.modules, "shared.twin_client", twin_mod)

    assert tt._get_twin_tenant_id() == "tenant_from_twin"
