"""Testes das tools de mapeamento de portas."""

from __future__ import annotations

from src.tools.portmap_tool import find_by_port, get_port_map

from .conftest import make_service


def test_get_port_map_empty(store):
    result = get_port_map(store)
    assert result["total"] == 0
    assert result["port_map"] == {}


def test_get_port_map_with_services(store):
    make_service(store, name="svc-a", port=8080)
    make_service(store, name="svc-b", port=9090)
    result = get_port_map(store)
    assert result["total"] == 2
    # Keys must be strings
    assert "8080" in result["port_map"]
    assert "9090" in result["port_map"]
    assert result["port_map"]["8080"]["name"] == "svc-a"
    assert result["port_map"]["9090"]["name"] == "svc-b"


def test_get_port_map_keys_are_strings(store):
    make_service(store, name="svc-a", port=3000)
    result = get_port_map(store)
    for key in result["port_map"]:
        assert isinstance(key, str)


def test_find_by_port_found(store):
    make_service(store, name="svc-a", port=8080)
    result = find_by_port(store, port=8080)
    assert result["found"] is True
    assert result["port"] == 8080
    assert result["service"]["name"] == "svc-a"


def test_find_by_port_not_found(store):
    result = find_by_port(store, port=9999)
    assert result["found"] is False
    assert result["port"] == 9999


def test_find_by_port_invalid_zero(store):
    result = find_by_port(store, port=0)
    assert result["error"] == "ValidationError"
    assert "port" in result["details"]


def test_find_by_port_invalid_too_large(store):
    result = find_by_port(store, port=70000)
    assert result["error"] == "ValidationError"
