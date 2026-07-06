"""Testes das tools de infraestrutura (register/scan/sync).

Herméticos: subprocess (docker) mockado; .env via tmp_path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.tools.infra_tool import (
    _detect_image_type,
    _parse_ports,
    _rebuild_redis_url,
    register_infra,
    scan_infra,
    sync_infra_env,
)

from .conftest import make_service

# ── helpers puros ─────────────────────────────────────────────────────────── #


def test_detect_image_type():
    assert _detect_image_type("mysql:8") == "mysql"
    assert _detect_image_type("bitnami/redis:7") == "redis"
    assert _detect_image_type("confluentinc/cp-kafka") == "kafka"
    assert _detect_image_type("nginx:latest") is None


def test_parse_ports():
    assert _parse_ports("0.0.0.0:9094->9092/tcp, :::9094->9092/tcp") == [
        (9094, 9092),
        (9094, 9092),
    ]


def test_rebuild_redis_url_scheme_preserves_db():
    assert _rebuild_redis_url("redis://old:1/5", "new", 6379) == "redis://new:6379/5"


def test_rebuild_redis_url_bare_host_port():
    assert _rebuild_redis_url("old:1", "new", 6379) == "new:6379"


# ── register_infra ────────────────────────────────────────────────────────── #


def test_register_infra_defaults(store):
    result = register_infra(store, name="mysql", kind="mysql")
    assert result["action"] == "created"
    assert result["port"] == 3306
    row = store.get("mysql")
    assert row["type"] == "mysql"


def test_register_infra_kafka_host_port(store):
    result = register_infra(store, name="kafka", kind="kafka")
    # kafka usa host_port EXTERNAL default 9094
    assert result["port"] == 9094


def test_register_infra_explicit_port(store):
    result = register_infra(store, name="pg", kind="postgres", port=5555)
    assert result["port"] == 5555


def test_register_infra_unknown_kind(store):
    result = register_infra(store, name="x", kind="cassandra")
    assert "error" in result


# ── scan_infra ────────────────────────────────────────────────────────────── #


def _docker_ps(*lines: str) -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = "\n".join(lines) + "\n"
    m.stderr = ""
    return m


def test_scan_infra_registers_detected(store):
    line_mysql = '{"ID":"a1","Names":"mysql-db","Image":"mysql:8","Ports":"0.0.0.0:3306->3306/tcp"}'
    line_app = '{"ID":"b2","Names":"myapp","Image":"myapp:1","Ports":"0.0.0.0:8080->80/tcp"}'
    with patch(
        "src.tools.infra_tool.subprocess.run",
        return_value=_docker_ps(line_mysql, line_app),
    ):
        result = scan_infra(store)
    assert result["scanned"] == 2
    assert len(result["registered"]) == 1
    assert result["registered"][0]["kind"] == "mysql"
    assert "myapp" in result["skipped_non_infra"]


def test_scan_infra_kafka_external_port(store):
    line = (
        '{"ID":"c3","Names":"kafka","Image":"cp-kafka:7",'
        '"Ports":"0.0.0.0:9094->9094/tcp, 0.0.0.0:9092->9092/tcp"}'
    )
    with patch("src.tools.infra_tool.subprocess.run", return_value=_docker_ps(line)):
        result = scan_infra(store)
    assert result["registered"][0]["port"] == 9094


def test_scan_infra_docker_not_found(store):
    with patch("src.tools.infra_tool.subprocess.run", side_effect=FileNotFoundError):
        result = scan_infra(store)
    assert result["error"] == "docker not found"


def test_scan_infra_nonzero_exit(store):
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = "daemon down"
    with patch("src.tools.infra_tool.subprocess.run", return_value=m):
        result = scan_infra(store)
    assert "error" in result


# ── sync_infra_env ────────────────────────────────────────────────────────── #


def test_sync_infra_env_file_not_found(store):
    result = sync_infra_env(store, path="/no/such/file.env")
    assert "error" in result


def test_sync_infra_env_mysql_db_vars(store, tmp_path):
    make_service(store, name="mysql", port=3306, type_="mysql")
    env = tmp_path / ".env"
    env.write_text("DB_ENGINE=mysql\nDB_HOST=oldhost\nDB_PORT=1111\n", encoding="utf-8")
    result = sync_infra_env(store, path=str(env))
    keys = {c["key"] for c in result["changes"]}
    assert "DB_HOST" in keys
    assert "DB_PORT" in keys
    content = env.read_text(encoding="utf-8")
    assert "DB_HOST=localhost" in content
    assert "DB_PORT=3306" in content


def test_sync_infra_env_postgres_database_url(store, tmp_path):
    make_service(store, name="postgres", port=5432, type_="postgres")
    env = tmp_path / ".env"
    env.write_text(
        "DB_ENGINE=postgres\nDATABASE_URL=postgresql://u:p@oldhost:9999/db\n",
        encoding="utf-8",
    )
    result = sync_infra_env(store, path=str(env))
    assert any(c["key"] == "DATABASE_URL" for c in result["changes"])
    assert "oldhost:9999" not in env.read_text(encoding="utf-8")


def test_sync_infra_env_kafka_and_redis(store, tmp_path):
    make_service(store, name="redis", port=6379, type_="redis")
    make_service(store, name="kafka", port=9094, type_="kafka")
    env = tmp_path / ".env"
    env.write_text("REDIS_URL=redis://old:1/2\nKAFKA_BOOTSTRAP_SERVERS=old:1\n", encoding="utf-8")
    result = sync_infra_env(store, path=str(env), db_kind="mysql")
    keys = {c["key"] for c in result["changes"]}
    assert "REDIS_URL" in keys
    assert "KAFKA_BOOTSTRAP_SERVERS" in keys


def test_sync_infra_env_dry_run(store, tmp_path):
    make_service(store, name="mysql", port=3306, type_="mysql")
    env = tmp_path / ".env"
    original = "DB_ENGINE=mysql\nDB_HOST=oldhost\n"
    env.write_text(original, encoding="utf-8")
    result = sync_infra_env(store, path=str(env), dry_run=True)
    assert result["dry_run"] is True
    assert result["changes"]
    assert env.read_text(encoding="utf-8") == original


def test_sync_infra_env_not_found(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("DB_ENGINE=mysql\nDB_HOST=oldhost\n", encoding="utf-8")
    result = sync_infra_env(store, path=str(env))
    assert "DB_HOST" in result["not_found_in_registry"]
