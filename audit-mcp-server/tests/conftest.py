"""Fixtures herméticas para a suíte de testes do audit-mcp.

Nenhum teste toca I/O externo: o PostgreSQL é substituído por um
``FakeAuditStore`` em memória que replica a API pública de ``AuditStore``.
Os testes que exercitam o código SQL real de ``AuditStore`` usam um pool
psycopg2 mockado (ver ``tests/test_store.py``).
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.config.settings import AuditSettings


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakeAuditStore:
    """Store em memória compatível com a API pública de ``AuditStore``.

    Usado nos testes de tools/gate/report/approval para mantê-los herméticos
    (sem PostgreSQL). O comportamento espelha o do store real: audit_id
    determinístico, checklist com items/approvals, criticidade default medium.
    """

    def __init__(self, settings: AuditSettings | None = None) -> None:
        self.settings = settings
        self._audits: dict[str, dict[str, Any]] = {}
        self._criticality: dict[str, str] = {}
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def create_audit(
        self,
        service: str,
        repo: str,
        env: str,
        criticality: str,
        score: float,
        passed: bool,
        status: str,
        checklist: dict[str, Any],
    ) -> str:
        audit_id = f"audit_{service}_{env}"
        now = _now()
        self._audits[audit_id] = {
            "id": audit_id,
            "service": service,
            "repo": repo,
            "env": env,
            "criticality": criticality,
            "score": score,
            "passed": passed,
            "status": status,
            "checklist": dict(checklist),
            "created_at": now,
            "updated_at": now,
        }
        return audit_id

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        row = self._audits.get(audit_id)
        return dict(row) if row else None

    def get_latest_audit(self, service: str, env: str) -> dict[str, Any] | None:
        matches = [a for a in self._audits.values() if a["service"] == service and a["env"] == env]
        if not matches:
            return None
        matches.sort(key=lambda a: a["created_at"], reverse=True)
        return dict(matches[0])

    def list_audits(
        self,
        status: str | None = None,
        env: str | None = None,
        service: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self._audits.values())
        if status:
            rows = [r for r in rows if r["status"] == status]
        if env:
            rows = [r for r in rows if r["env"] == env]
        if service:
            rows = [r for r in rows if r["service"] == service]
        rows.sort(key=lambda a: a["created_at"], reverse=True)
        return [dict(r) for r in rows[offset : offset + limit]]

    def update_audit_status(self, audit_id: str, status: str, score: float, passed: bool) -> None:
        row = self._audits.get(audit_id)
        if row:
            row["status"] = status
            row["score"] = score
            row["passed"] = passed
            row["updated_at"] = _now()

    def add_audit_item(
        self,
        audit_id: str,
        category: str,
        name: str,
        required: bool,
        passed: bool,
        details: str | None = None,
    ) -> None:
        row = self._audits.get(audit_id)
        if row:
            row["checklist"].setdefault("items", []).append(
                {
                    "category": category,
                    "name": name,
                    "required": required,
                    "passed": passed,
                    "details": details,
                }
            )

    def get_audit_items(self, audit_id: str) -> list[dict[str, Any]]:
        row = self._audits.get(audit_id)
        if row:
            return row["checklist"].get("items", [])
        return []

    def add_approval(
        self,
        audit_id: str,
        approved_by: str,
        decision: str,
        role: str | None = None,
        notes: str | None = None,
    ) -> None:
        row = self._audits.get(audit_id)
        if row:
            row["checklist"].setdefault("approvals", []).append(
                {
                    "approved_by": approved_by,
                    "role": role,
                    "decision": decision,
                    "notes": notes,
                    "created_at": _now(),
                }
            )

    def get_approvals(self, audit_id: str) -> list[dict[str, Any]]:
        row = self._audits.get(audit_id)
        if row:
            return row["checklist"].get("approvals", [])
        return []

    def set_service_criticality(self, service: str, criticality: str, updated_by: str) -> None:
        # Espelha o store real, que não persiste (retorna sempre "medium").
        self._criticality[service] = criticality

    def get_service_criticality(self, service: str) -> str:
        return "medium"


@pytest.fixture
def tmp_repo():
    """Cria repo temporário com estrutura básica."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "pyproject.toml").write_text("[project]\nname = 'test'", encoding="utf-8")
        (repo / "README.md").write_text("# Test Repo", encoding="utf-8")
        yield repo


@pytest.fixture
def settings(tmp_path):
    """Configurações para testes (aponta para as policies reais do repo)."""
    return AuditSettings(
        pg_host="localhost",
        pg_port=5432,
        pg_db="app",
        pg_user="postgres",
        pg_password="test",
        pg_min_conn=1,
        pg_max_conn=5,
        github_token="test_token",
        policies_path=str(Path(__file__).parent.parent / "src" / "policies"),
    )


@pytest.fixture
def store(settings):
    """Store hermético em memória (sem PostgreSQL)."""
    fake = FakeAuditStore(settings=settings)
    yield fake
    fake.close()
