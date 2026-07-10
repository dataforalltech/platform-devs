"""Fixtures compartilhadas para todos os testes do services-mcp-server.

Os testes são herméticos: nenhuma I/O externa (PostgreSQL, rede, subprocess) é
executada. O `ServiceStore` real abre um pool psycopg2 contra um PostgreSQL no
`__init__`, então usamos um store in-memory (`InMemoryServiceStore`) que replica
fielmente o contrato público do store (upsert/get/list_all/delete/update_check/
close), incluindo a serialização JSON de tags/metadata e a semântica de
created/updated. Assim o código das tools e o dispatch rodam sem tocar no banco.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from src.config.settings import ServicesSettings

# Colunas do schema `services` (ver ServiceStore._migrate) com seus defaults.
# Toda row retornada pelo store real sempre tem todas as colunas presentes.
_COLUMN_DEFAULTS: dict[str, Any] = {
    "host": "localhost",
    "port": None,
    "url": None,
    "internal_url": None,
    "type": "unknown",
    "container_name": None,
    "pid": None,
    "status": "unknown",
    "health_path": "/health",
    "environment": "local",
    "tags": "[]",
    "metadata": "{}",
    "registered_at": None,
    "last_seen": None,
    "last_check_at": None,
    "last_check_ok": None,
    "runtime": "unknown",
    "os_name": None,
    "os_release": None,
    "hostname": None,
    "deploy_mode": None,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class InMemoryServiceStore:
    """Réplica in-memory do ServiceStore.

    Mesmo contrato público, mesma semântica de serialização e de create/update,
    porém sem PostgreSQL — mantém as rows num dict em memória.
    """

    def __init__(self, db_path: str = ":memory:", dsn: str | None = None) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self.closed = False

    @staticmethod
    def _serialize(fields: dict[str, Any]) -> dict[str, Any]:
        out = dict(fields)
        if isinstance(out.get("tags"), list):
            out["tags"] = json.dumps(out["tags"])
        if isinstance(out.get("metadata"), dict):
            out["metadata"] = json.dumps(out["metadata"])
        return out

    def upsert(self, name: str, fields: dict[str, Any]) -> dict[str, Any]:
        existing = self._rows.get(name)
        if existing is None:
            row = dict(_COLUMN_DEFAULTS)
            row["name"] = name
            row.update(self._serialize(fields))
            row.setdefault("registered_at", _now())
            self._rows[name] = row
            action = "created"
        else:
            existing.update(self._serialize(fields))
            existing["last_seen"] = _now()
            action = "updated"
        return {"action": action, "row": dict(self._rows[name])}

    def get(self, name: str) -> dict | None:
        row = self._rows.get(name)
        return dict(row) if row else None

    def list_all(
        self,
        environment: str | None = None,
        type_: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        runtime: str | None = None,
        deploy_mode: str | None = None,
    ) -> list[dict]:
        rows = [dict(r) for r in self._rows.values()]
        if environment:
            rows = [r for r in rows if r.get("environment") == environment]
        if type_:
            rows = [r for r in rows if r.get("type") == type_]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if runtime:
            rows = [r for r in rows if r.get("runtime") == runtime]
        if deploy_mode:
            rows = [r for r in rows if r.get("deploy_mode") == deploy_mode]
        rows.sort(key=lambda r: r["name"])
        if tag:
            rows = [r for r in rows if tag in json.loads(r.get("tags") or "[]")]
        return rows

    def delete(self, name: str) -> bool:
        return self._rows.pop(name, None) is not None

    def update_check(self, name: str, ok: bool) -> None:
        row = self._rows.get(name)
        if row is not None:
            row["last_check_at"] = _now()
            row["last_check_ok"] = 1 if ok else 0

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def store():
    s = InMemoryServiceStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def settings():
    return ServicesSettings(db_path=":memory:", health_timeout=2.0, docker_timeout=5)


def make_service(
    store: InMemoryServiceStore,
    name: str = "api-gateway",
    port: int = 8080,
    environment: str = "local",
    type_: str = "docker",
    status: str = "running",
    tags: list[str] | None = None,
) -> None:
    """Helper para registrar serviço nos testes."""
    from src.tools.registry_tool import register_service

    register_service(
        store,
        name=name,
        host="localhost",
        port=port,
        url=f"http://localhost:{port}",
        type=type_,
        environment=environment,
        health_path="/health",
        tags=tags or [],
        metadata={},
        status=status,
    )
