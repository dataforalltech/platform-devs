"""Infra: register_infra / scan_infra / sync_infra_env contra MySQL real (FID-02).

docker é o único duplo; o registry e o parsing de .env são reais.
"""

from __future__ import annotations

import json

import pytest

from src.tools import infra_tool
from src.tools.infra_tool import register_infra, scan_infra, sync_infra_env

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── register_infra ────────────────────────────────────────────────────────────
async def test_register_infra_mysql_defaults(store_a):
    result = await register_infra(store_a, name="db", kind="mysql")
    assert result["action"] == "created"
    assert result["port"] == 3306
    row = await store_a.get("db")
    assert row["type"] == "mysql"
    meta = json.loads(row["metadata"])
    assert meta["protocol"] == "mysql"


async def test_register_infra_kafka_host_port(store_a):
    result = await register_infra(store_a, name="kafka", kind="kafka", container_name="kafka-ctr")
    assert result["port"] == 9094  # host_port EXTERNAL como porta resolvida
    row = await store_a.get("kafka")
    meta = json.loads(row["metadata"])
    assert meta["host_port"] == 9094
    assert row["container_name"] == "kafka-ctr"


async def test_register_infra_explicit_port_and_metadata(store_a):
    result = await register_infra(store_a, name="redis", kind="redis", port=6380, metadata={"note": "custom"})
    assert result["port"] == 6380
    meta = json.loads((await store_a.get("redis"))["metadata"])
    assert meta["note"] == "custom"


async def test_register_infra_unknown_kind(store_a):
    result = await register_infra(store_a, name="x", kind="cassandra")
    assert "error" in result


# ── scan_infra ────────────────────────────────────────────────────────────────
async def test_scan_infra_docker_missing(store_a, monkeypatch):
    def _boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(infra_tool.subprocess, "run", _boom)
    result = await scan_infra(store_a)
    assert result["error"] == "docker not found"


async def test_scan_infra_success(store_a, monkeypatch):
    lines = "\n".join(
        json.dumps(c)
        for c in (
            {"Names": "db", "Image": "mysql:8", "Ports": "0.0.0.0:3306->3306/tcp"},
            {"Names": "kafka", "Image": "confluentinc/cp-kafka", "Ports": "0.0.0.0:9094->9094/tcp"},
            {"Names": "auth", "Image": "platform-auth:latest", "Ports": ""},
        )
    )
    monkeypatch.setattr(infra_tool.subprocess, "run", lambda *a, **k: _FakeProc(stdout=lines + "\n"))
    result = await scan_infra(store_a)
    kinds = {r["kind"] for r in result["registered"]}
    assert kinds == {"mysql", "kafka"}
    assert "auth" in result["skipped_non_infra"]
    kafka_reg = next(r for r in result["registered"] if r["kind"] == "kafka")
    assert kafka_reg["port"] == 9094


# ── sync_infra_env ────────────────────────────────────────────────────────────
async def test_sync_infra_env_file_missing(store_a, tmp_path):
    result = await sync_infra_env(store_a, path=str(tmp_path / "nope.env"))
    assert "error" in result


async def test_sync_infra_env_mysql_redis_kafka(store_a, tmp_path):
    await register_infra(store_a, name="db", kind="mysql", host="localhost", port=3306)
    await register_infra(store_a, name="redis", kind="redis", host="localhost", port=6379)
    await register_infra(store_a, name="kafka", kind="kafka", host="localhost")

    p = tmp_path / ".env"
    p.write_text(
        "DB_ENGINE=mysql\n"
        "DB_HOST=old-host\n"
        "DB_PORT=1\n"
        "REDIS_URL=redis://old:1/2\n"
        "KAFKA_BOOTSTRAP_SERVERS=old:1\n",
        encoding="utf-8",
    )
    result = await sync_infra_env(store_a, path=str(p))
    changed = {c["key"] for c in result["changes"]}
    assert {"DB_HOST", "DB_PORT", "REDIS_URL", "KAFKA_BOOTSTRAP_SERVERS"} <= changed
    content = p.read_text(encoding="utf-8")
    assert "DB_HOST=localhost" in content
    assert "DB_PORT=3306" in content
    assert "REDIS_URL=redis://localhost:6379/2" in content  # /db preservado
    assert "KAFKA_BOOTSTRAP_SERVERS=localhost:9094" in content


async def test_sync_infra_env_dry_run_and_not_found(store_a, tmp_path):
    # registry vazio → tudo not_found; dry_run não escreve.
    p = tmp_path / ".env"
    p.write_text("DB_HOST=old\nREDIS_URL=redis://old:1/0\n", encoding="utf-8")
    result = await sync_infra_env(store_a, path=str(p), dry_run=True, db_kind="mysql")
    assert "DB_HOST" in result["not_found_in_registry"]
    assert "DB_HOST=old" in p.read_text(encoding="utf-8")


async def test_sync_infra_env_postgres_database_url(store_a, tmp_path):
    await register_infra(store_a, name="pg", kind="postgres", host="localhost", port=5432)
    p = tmp_path / ".env"
    p.write_text("DB_ENGINE=postgres\nDATABASE_URL=postgresql://u:p@old-host:5432/db\n", encoding="utf-8")
    result = await sync_infra_env(store_a, path=str(p))
    assert result["db_type_used"] == "postgres"
    assert "postgresql://u:p@localhost:5432/db" in p.read_text(encoding="utf-8")
