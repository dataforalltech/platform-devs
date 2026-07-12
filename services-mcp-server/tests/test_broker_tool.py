"""Brokers: kafka_status / redis_status / sync_broker_urls.

Banco real (FID-02); as conexões TCP (socket) são o único duplo.
"""

from __future__ import annotations

import pytest

from src.tools import broker_tool
from src.tools.broker_tool import (
    _parse_bootstrap,
    _parse_redis_url,
    _tcp_ping,
    kafka_status,
    redis_status,
    sync_broker_urls,
)
from src.tools.infra_tool import register_infra

from .conftest import requires_mysql


class _FakeSock:
    def __init__(self, recv_bytes: bytes = b"+PONG\r\n") -> None:
        self._recv = recv_bytes
        self.sent: bytes = b""

    def __enter__(self) -> _FakeSock:
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def sendall(self, data: bytes) -> None:
        self.sent = data

    def recv(self, _n: int) -> bytes:
        return self._recv


def _patch_socket_ok(monkeypatch, recv_bytes: bytes = b"+PONG\r\n") -> None:
    monkeypatch.setattr(broker_tool.socket, "create_connection", lambda *a, **k: _FakeSock(recv_bytes))


def _patch_socket_fail(monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise OSError("refused")

    monkeypatch.setattr(broker_tool.socket, "create_connection", _boom)


# ── helpers puros ─────────────────────────────────────────────────────────────
def test_parse_bootstrap():
    assert _parse_bootstrap("h1:1,h2:2") == [("h1", 1), ("h2", 2)]
    assert _parse_bootstrap("bad,h:3") == [("h", 3)]


def test_parse_redis_url():
    assert _parse_redis_url("redis://host:6380/1") == ("host", 6380)
    assert _parse_redis_url("host:1234") == ("host", 1234)
    assert _parse_redis_url("plain") == ("plain", 6379)


def test_tcp_ping(monkeypatch):
    _patch_socket_ok(monkeypatch)
    ok, latency = _tcp_ping("h", 1)
    assert ok is True
    assert latency >= 0
    _patch_socket_fail(monkeypatch)
    ok, _ = _tcp_ping("h", 1)
    assert ok is False


# ── kafka_status ──────────────────────────────────────────────────────────────
async def test_kafka_status_explicit_servers(monkeypatch):
    _patch_socket_ok(monkeypatch)
    result = await kafka_status(None, bootstrap_servers="localhost:9092,localhost:9093")
    assert result["ok"] is True
    assert len(result["brokers"]) == 2
    assert result["brokers"][0]["reachable"] is True


async def test_kafka_status_unreachable(monkeypatch):
    _patch_socket_fail(monkeypatch)
    result = await kafka_status(None, bootstrap_servers="localhost:9092")
    assert result["ok"] is False


@pytest.mark.integration
@requires_mysql
async def test_kafka_status_from_registry(store_a, monkeypatch):
    _patch_socket_ok(monkeypatch)
    await register_infra(store_a, name="kafka", kind="kafka", host="localhost", port=9094)
    result = await kafka_status(store_a)
    assert result["ok"] is True
    assert result["bootstrap_servers"] == "localhost:9094"


@pytest.mark.integration
@requires_mysql
async def test_kafka_status_not_in_registry(store_a):
    result = await kafka_status(store_a)
    assert result["ok"] is False
    assert "error" in result


# ── redis_status ──────────────────────────────────────────────────────────────
async def test_redis_status_explicit_url(monkeypatch):
    _patch_socket_ok(monkeypatch)
    result = await redis_status(None, url="redis://localhost:6379/0")
    assert result["ok"] is True
    assert result["resp"]["ping"] == "+PONG"


async def test_redis_status_unreachable(monkeypatch):
    _patch_socket_fail(monkeypatch)
    result = await redis_status(None, url="redis://localhost:6379/0")
    assert result["ok"] is False
    assert result["reachable"] is False


@pytest.mark.integration
@requires_mysql
async def test_redis_status_from_registry(store_a, monkeypatch):
    _patch_socket_ok(monkeypatch)
    await register_infra(store_a, name="redis", kind="redis", host="localhost", port=6379)
    result = await redis_status(store_a)
    assert result["ok"] is True
    assert result["host"] == "localhost"


@pytest.mark.integration
@requires_mysql
async def test_redis_status_not_in_registry(store_a):
    result = await redis_status(store_a)
    assert result["ok"] is False
    assert "error" in result


# ── sync_broker_urls ──────────────────────────────────────────────────────────
async def test_sync_broker_urls_file_missing(tmp_path):
    result = await sync_broker_urls(None, path=str(tmp_path / "nope.env"))
    assert "error" in result


@pytest.mark.integration
@requires_mysql
async def test_sync_broker_urls_changes(store_a, tmp_path):
    await register_infra(store_a, name="kafka", kind="kafka", host="localhost", port=9094)
    await register_infra(store_a, name="redis", kind="redis", host="localhost", port=6379)
    p = tmp_path / ".env"
    p.write_text(
        "KAFKA_BOOTSTRAP_SERVERS=old:1\nREDIS_URL=redis://old:1/5\nCACHE_URL=old:1\n", encoding="utf-8"
    )
    result = await sync_broker_urls(store_a, path=str(p))
    changed = {c["key"] for c in result["changes"]}
    assert "KAFKA_BOOTSTRAP_SERVERS" in changed
    assert "REDIS_URL" in changed
    content = p.read_text(encoding="utf-8")
    assert "KAFKA_BOOTSTRAP_SERVERS=localhost:9094" in content
    assert "REDIS_URL=redis://localhost:6379/5" in content


@pytest.mark.integration
@requires_mysql
async def test_sync_broker_urls_not_found_dry_run(store_a, tmp_path):
    p = tmp_path / ".env"
    p.write_text("KAFKA_BOOTSTRAP_SERVERS=old:1\n", encoding="utf-8")
    result = await sync_broker_urls(store_a, path=str(p), dry_run=True)
    assert "KAFKA_BOOTSTRAP_SERVERS" in result["not_found_in_registry"]
    assert "old:1" in p.read_text(encoding="utf-8")
