"""Fixtures compartilhadas para os testes do pipeline-mcp-server.

Os testes são HERMÉTICOS: nada toca PostgreSQL, GitHub ou a rede reais.

  * As tools (`src/tools/*`) recebem um `store` e só chamam métodos dele —
    então usamos um `FakePipelineStore` in-memory que implementa exatamente
    a mesma interface pública que `PipelineStore`.
  * `PipelineStore` (psycopg2) é exercitado à parte em `test_store.py`,
    onde o pool/conexão/cursor são mockados.
  * As chamadas ao GitHub passam por `httpx.Client`, mockado nos testes que
    exercitam `promote_service` / `approve_promotion` / `watch_prs`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from src.config.settings import PipelineSettings
from src.db.store import DEFAULT_GATES


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakePipelineStore:
    """Store in-memory com a mesma interface pública usada pelas tools.

    Reproduz a semântica do PostgreSQL store real (gates_config como dict,
    promotions com id auto-incremental, upsert de gate por chave única, etc.)
    sem tocar em nenhum banco.
    """

    def __init__(self) -> None:
        self.pipelines: dict[str, dict[str, Any]] = {}
        self.promotions: list[dict[str, Any]] = []
        self.gates: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._promo_seq = 0
        self.closed = False

    # ── Pipelines ──────────────────────────────────────────────────────── #

    def register_pipeline(self, service: str, repo: str, base_branch: str = "develop") -> dict:
        now = _now()
        if service not in self.pipelines:
            self.pipelines[service] = {
                "service": service,
                "repo": repo,
                "base_branch": base_branch,
                "current_env": "dev",
                "current_version": None,
                "blocked": 0,
                "block_reason": None,
                "blocked_by": None,
                "blocked_at": None,
                "gates_config": json.loads(json.dumps(DEFAULT_GATES)),
                "registered_at": now,
                "updated_at": now,
            }
            action = "created"
        else:
            self.pipelines[service].update(
                {"repo": repo, "base_branch": base_branch, "updated_at": now}
            )
            action = "updated"
        return {"action": action, "pipeline": dict(self.pipelines[service])}

    def get_pipeline(self, service: str) -> dict | None:
        p = self.pipelines.get(service)
        if p is None:
            return None
        result = dict(p)
        result["recent_promotions"] = [
            dict(pr) for pr in self.promotions if pr["service"] == service
        ][-10:]
        return result

    def list_pipelines(self, env: str | None = None, status: str | None = None) -> list[dict]:
        rows = list(self.pipelines.values())
        if env:
            rows = [r for r in rows if r["current_env"] == env]
        if status == "blocked":
            rows = [r for r in rows if r["blocked"] == 1]
        elif status == "active":
            rows = [r for r in rows if r["blocked"] == 0]
        return [dict(r) for r in sorted(rows, key=lambda r: r["service"])]

    def update_pipeline_env(self, service: str, env: str, version: str | None = None) -> None:
        if service in self.pipelines:
            self.pipelines[service]["current_env"] = env
            self.pipelines[service]["current_version"] = version
            self.pipelines[service]["updated_at"] = _now()

    def block_pipeline(self, service: str, reason: str, blocked_by: str) -> dict:
        now = _now()
        p = self.pipelines[service]
        p.update(
            {
                "blocked": 1,
                "block_reason": reason,
                "blocked_by": blocked_by,
                "blocked_at": now,
                "updated_at": now,
            }
        )
        return dict(p)

    def set_gates_config(self, service: str, gates_required: dict) -> dict:
        p = self.pipelines[service]
        p["gates_config"] = json.loads(json.dumps(gates_required))
        p["updated_at"] = _now()
        return dict(p)

    # ── Promotions ─────────────────────────────────────────────────────── #

    def add_promotion(
        self,
        service: str,
        from_env: str,
        to_env: str,
        promoted_by: str,
        reason: str | None,
        gates_snapshot: dict,
        deploy_ref: str | None,
        status: str,
        pr_number: int | None = None,
        pr_url: str | None = None,
    ) -> int:
        self._promo_seq += 1
        self.promotions.append(
            {
                "id": self._promo_seq,
                "service": service,
                "from_env": from_env,
                "to_env": to_env,
                "promoted_by": promoted_by,
                "reason": reason,
                "gates_snapshot": json.dumps(gates_snapshot),
                "deploy_ref": deploy_ref,
                "pr_number": pr_number,
                "pr_url": pr_url,
                "approved_by": None,
                "approved_at": None,
                "status": status,
                "created_at": _now(),
                "completed_at": None,
            }
        )
        return self._promo_seq

    def _find_promo(self, promotion_id: int) -> dict | None:
        for pr in self.promotions:
            if pr["id"] == promotion_id:
                return pr
        return None

    def complete_promotion(self, promotion_id: int, status: str) -> None:
        pr = self._find_promo(promotion_id)
        if pr:
            pr["status"] = status
            pr["completed_at"] = _now()

    def approve_promotion(self, promotion_id: int, approved_by: str) -> dict | None:
        pr = self._find_promo(promotion_id)
        if pr is None:
            return None
        now = _now()
        pr.update(
            {
                "approved_by": approved_by,
                "approved_at": now,
                "status": "approved",
                "completed_at": now,
            }
        )
        return dict(pr)

    def get_promotion(self, promotion_id: int) -> dict | None:
        pr = self._find_promo(promotion_id)
        return dict(pr) if pr else None

    def get_promotion_history(self, service: str | None = None, limit: int = 20) -> list[dict]:
        rows = self.promotions
        if service:
            rows = [r for r in rows if r["service"] == service]
        # ordem decrescente por created_at (mais recente primeiro)
        ordered = sorted(rows, key=lambda r: r["id"], reverse=True)
        return [dict(r) for r in ordered[:limit]]

    # ── Gates ──────────────────────────────────────────────────────────── #

    def upsert_gate(
        self,
        service: str,
        env: str,
        gate_type: str,
        passed: bool,
        details: str | None = None,
        evaluated_by: str | None = None,
    ) -> dict:
        key = (service, env, gate_type)
        self.gates[key] = {
            "id": len(self.gates) + 1,
            "service": service,
            "env": env,
            "gate_type": gate_type,
            "passed": 1 if passed else 0,
            "details": details,
            "evaluated_by": evaluated_by,
            "evaluated_at": _now(),
        }
        return dict(self.gates[key])

    def get_gates(self, service: str, env: str) -> list[dict]:
        rows = [dict(v) for (s, e, _), v in self.gates.items() if s == service and e == env]
        return sorted(rows, key=lambda r: r["gate_type"])

    def clear_gates(self, service: str, env: str) -> int:
        keys = [k for k in self.gates if k[0] == service and k[1] == env]
        for k in keys:
            del self.gates[k]
        return len(keys)

    def get_pipeline_overview(self) -> dict:
        overview: dict[str, Any] = {}
        total = 0
        for p in self.pipelines.values():
            env = p["current_env"]
            total += 1
            bucket = overview.setdefault(env, {"total": 0, "blocked": 0, "active": 0})
            bucket["total"] += 1
            if p["blocked"]:
                bucket["blocked"] += 1
            else:
                bucket["active"] += 1
        failed = [
            {"service": g["service"], "env": g["env"], "failed": 1}
            for g in self.gates.values()
            if not g["passed"]
        ]
        return {
            "total_services": total,
            "by_env": overview,
            "services_with_failed_gates": failed,
        }

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def store() -> FakePipelineStore:
    """Store in-memory hermético, com a mesma interface do PipelineStore."""
    return FakePipelineStore()


@pytest.fixture
def registered_store(store: FakePipelineStore) -> FakePipelineStore:
    """Store com um serviço já registrado em 'dev'."""
    store.register_pipeline(service="svc-a", repo="test-org/svc-a", base_branch="develop")
    return store


@pytest.fixture
def settings() -> PipelineSettings:
    """Settings sem token/org (GitHub indisponível por padrão)."""
    return PipelineSettings(github_token="", github_org="")


@pytest.fixture
def settings_with_github() -> PipelineSettings:
    return PipelineSettings(github_token="ghp_test_token", github_org="test-org")


class FakeResponse:
    """Resposta HTTP falsa no formato que o httpx.Client retorna."""

    def __init__(self, status_code: int, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or json.dumps(self._json)

    def json(self) -> Any:
        return self._json


class FakeHTTPClient:
    """Context-manager que imita httpx.Client, devolvendo respostas pré-carregadas."""

    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        # responses: mapa "METHOD" -> FakeResponse
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> FakeHTTPClient:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def _record(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        resp = self._responses.get(method)
        if resp is None:
            raise AssertionError(f"Unexpected {method} to {url}")
        return resp

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record("PUT", url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record("GET", url, **kwargs)
