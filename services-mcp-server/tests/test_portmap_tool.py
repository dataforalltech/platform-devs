"""Tools de mapeamento de portas contra MySQL real (§16 / FID-02)."""

from __future__ import annotations

import pytest

from src.tools.portmap_tool import find_by_port, get_port_map
from src.tools.registry_tool import register_service

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


async def test_get_port_map(store_a):
    await register_service(store_a, name="a", port=8080, type="docker")
    await register_service(store_a, name="b", port=9090, type="process")
    result = await get_port_map(store_a)
    assert result["total"] == 2
    assert result["port_map"]["8080"]["name"] == "a"
    assert result["port_map"]["9090"]["type"] == "process"


async def test_get_port_map_ignores_portless(store_a):
    # register_infra-less path: registrar via store direto sem porta.
    await store_a.upsert("portless", {"type": "remote"})
    result = await get_port_map(store_a)
    assert result["total"] == 0


async def test_find_by_port_found(store_a):
    await register_service(store_a, name="a", port=8080)
    result = await find_by_port(store_a, port=8080)
    assert result["found"] is True
    assert result["service"]["name"] == "a"


async def test_find_by_port_not_found(store_a):
    result = await find_by_port(store_a, port=1234)
    assert result == {"found": False, "port": 1234}


async def test_find_by_port_invalid(store_a):
    assert (await find_by_port(store_a, port=0))["error"] == "ValidationError"
    assert (await find_by_port(store_a, port=99999))["error"] == "ValidationError"
