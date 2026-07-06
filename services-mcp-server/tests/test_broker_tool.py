"""Testes das tools de brokers (Kafka/Redis).

Herméticos: toda I/O de socket é mockada com monkeypatch.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.tools import broker_tool
from src.tools.broker_tool import (
    _parse_bootstrap,
    _parse_redis_url,
    kafka_status,
    redis_status,
    sync_broker_urls,
)

from .conftest import make_service

# ── helpers puros ─────────────────────────────────────────────────────────── #


def test_parse_bootstrap_multiple():
    assert _parse_bootstrap("h1:9092, h2:9093") == [("h1", 9092), ("h2", 9093)]


def test_parse_bootstrap_ignores_malformed():
    assert _parse_bootstrap("h1:9092,bad,h2:notaport") == [("h1", 9092)]


def test_parse_redis_url_scheme():
    assert _parse_redis_url("redis://cache:6380/1") == ("cache", 6380)


def test_parse_redis_url_host_port():
    assert _parse_redis_url("myhost:6390") == ("myhost", 6390)


def test_parse_redis_url_bare_host_defaults_port():
    assert _parse_redis_url("localhost") == ("localhost", 6379)


# ── kafka_status ──────────────────────────────────────────────────────────── #


def test_kafka_status_explicit_reachable(store):
    with patch.object(broker_tool, "_tcp_ping", return_value=(True, 3.14)):
        result = kafka_status(store, bootstrap_servers="broker:9092")
    assert result["ok"] is True
    assert result["brokers"][0]["reachable"] is True
    assert result["brokers"][0]["broker"] == "broker:9092"


def test_kafka_status_unreachable(store):
    with patch.object(broker_tool, "_tcp_ping", return_value=(False, 2000.0)):
        result = kafka_status(store, bootstrap_servers="broker:9092")
    assert result["ok"] is False


def test_kafka_status_from_registry(store):
    make_service(store, name="kafka", port=9092, type_="kafka")
    with patch.object(broker_tool, "_tcp_ping", return_value=(True, 1.0)):
        result = kafka_status(store)
    assert result["ok"] is True
    assert result["bootstrap_servers"] == "localhost:9092"


def test_kafka_status_not_found(store):
    result = kafka_status(store)
    assert result["ok"] is False
    assert "error" in result


# ── redis_status ──────────────────────────────────────────────────────────── #


def test_redis_status_reachable_ping(store):
    sock = MagicMock()
    sock.__enter__ = MagicMock(return_value=sock)
    sock.__exit__ = MagicMock(return_value=False)
    sock.recv.return_value = b"+PONG\r\n"

    with (
        patch.object(broker_tool, "_tcp_ping", return_value=(True, 0.5)),
        patch.object(broker_tool.socket, "create_connection", return_value=sock),
    ):
        result = redis_status(store, url="redis://localhost:6379/0")

    assert result["ok"] is True
    assert result["reachable"] is True
    assert result["resp"]["ping"] == "+PONG"


def test_redis_status_unreachable(store):
    with patch.object(broker_tool, "_tcp_ping", return_value=(False, 100.0)):
        result = redis_status(store, url="redis://localhost:6379/0")
    assert result["ok"] is False
    assert result["reachable"] is False


def test_redis_status_from_registry(store):
    make_service(store, name="redis", port=6379, type_="redis")
    with (
        patch.object(broker_tool, "_tcp_ping", return_value=(True, 0.5)),
        patch.object(broker_tool.socket, "create_connection", side_effect=OSError("boom")),
    ):
        result = redis_status(store)
    # TCP ok, mas RESP ping falhou → ainda ok=True com ping_error
    assert result["ok"] is True
    assert "ping_error" in result["resp"]


def test_redis_status_not_found(store):
    result = redis_status(store)
    assert result["ok"] is False
    assert "error" in result


# ── sync_broker_urls ──────────────────────────────────────────────────────── #


def test_sync_broker_urls_file_not_found(store):
    result = sync_broker_urls(store, path="/no/such/file.env")
    assert "error" in result


def test_sync_broker_urls_updates_kafka_and_redis(store, tmp_path):
    make_service(store, name="kafka", port=9092, type_="kafka")
    make_service(store, name="redis", port=6379, type_="redis")

    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "KAFKA_BOOTSTRAP_SERVERS=old:1111\n"
        "REDIS_URL=redis://old:2222/3\n"
        "UNRELATED=keepme\n",
        encoding="utf-8",
    )

    result = sync_broker_urls(store, path=str(env), dry_run=False)
    keys = {c["key"] for c in result["changes"]}
    assert "KAFKA_BOOTSTRAP_SERVERS" in keys
    assert "REDIS_URL" in keys

    content = env.read_text(encoding="utf-8")
    assert "KAFKA_BOOTSTRAP_SERVERS=localhost:9092" in content
    # preserva o /db=3 da URL redis
    assert "REDIS_URL=redis://localhost:6379/3" in content
    assert "UNRELATED=keepme" in content


def test_sync_broker_urls_dry_run_does_not_write(store, tmp_path):
    make_service(store, name="kafka", port=9092, type_="kafka")
    env = tmp_path / ".env"
    original = "KAFKA_BOOTSTRAP_SERVERS=old:1111\n"
    env.write_text(original, encoding="utf-8")

    result = sync_broker_urls(store, path=str(env), dry_run=True)
    assert result["dry_run"] is True
    assert result["changes"]
    assert env.read_text(encoding="utf-8") == original


def test_sync_broker_urls_skips_already_correct(store, tmp_path):
    make_service(store, name="kafka", port=9092, type_="kafka")
    env = tmp_path / ".env"
    env.write_text("KAFKA_BOOTSTRAP_SERVERS=localhost:9092\n", encoding="utf-8")

    result = sync_broker_urls(store, path=str(env))
    assert "KAFKA_BOOTSTRAP_SERVERS" in result["skipped_already_correct"]
    assert result["changes"] == []


def test_sync_broker_urls_not_found_in_registry(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("KAFKA_BOOTSTRAP_SERVERS=old:1111\n", encoding="utf-8")
    result = sync_broker_urls(store, path=str(env))
    assert "KAFKA_BOOTSTRAP_SERVERS" in result["not_found_in_registry"]
