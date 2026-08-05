# Portado de `services-mcp-server/tests/test_models.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Modelo canônico do registry (`ServiceRow`) + coerção `service_record` (JSON de
tags/metadata e o bool de last_check_ok)."""

from __future__ import annotations

from src.domains.services.models.service import ServiceRow, service_record


def _row(**over: object) -> dict:
    base: dict[str, object] = {
        "name": "svc",
        "host": "localhost",
        "port": 8080,
        "type": "docker",
        "status": "running",
        "environment": "local",
        "tags": '["web", "api"]',
        "metadata": '{"image": "nginx"}',
        "last_check_ok": 1,
    }
    base.update(over)
    return base


def test_service_record_parses_json_and_bool():
    rec = service_record(_row())
    assert rec["name"] == "svc"
    assert rec["port"] == 8080
    assert rec["tags"] == ["web", "api"]
    assert rec["metadata"] == {"image": "nginx"}
    assert rec["last_check_ok"] is True
    # runtime/deploy_mode default para "unknown" quando ausentes/None
    assert rec["runtime"] == "unknown"
    assert rec["deploy_mode"] == "unknown"


def test_service_record_defaults_for_empty_json():
    rec = service_record(_row(tags=None, metadata=None, last_check_ok=None))
    assert rec["tags"] == []
    assert rec["metadata"] == {}
    assert rec["last_check_ok"] is None


def test_service_record_last_check_ok_false():
    assert service_record(_row(last_check_ok=0))["last_check_ok"] is False


def test_service_record_passthrough_optional_fields():
    rec = service_record(
        _row(
            url="http://localhost:8080",
            internal_url="http://svc:8080",
            container_name="svc",
            pid=1234,
            health_path="/health",
            runtime="uvicorn",
            deploy_mode="asgi",
            os_name="linux",
            os_release="6.0",
            hostname="host1",
            registered_at="2026-01-01",
            last_seen="2026-01-02",
            last_check_at="2026-01-03",
        )
    )
    assert rec["url"] == "http://localhost:8080"
    assert rec["internal_url"] == "http://svc:8080"
    assert rec["container_name"] == "svc"
    assert rec["pid"] == 1234
    assert rec["runtime"] == "uvicorn"
    assert rec["deploy_mode"] == "asgi"
    assert rec["os_name"] == "linux"
    assert rec["hostname"] == "host1"


def test_service_row_ignores_extra_fields():
    # extra="ignore": colunas de auditoria injetadas pela fábrica não quebram o parse.
    row = ServiceRow(name="svc", id_user_created=0, create_on="2026")  # type: ignore[call-arg]
    assert row.name == "svc"
    assert row.host is None
