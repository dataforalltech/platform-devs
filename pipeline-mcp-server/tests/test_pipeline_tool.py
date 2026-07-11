"""Pipeline tools (async) contra store MySQL real; GitHub (externo) mockado."""

from __future__ import annotations

import pytest

import src.tools.pipeline_tool as PT
from src.tools import (
    approve_promotion,
    block_service,
    get_pipeline,
    get_pipeline_overview,
    get_promotion_history,
    list_pipeline,
    promote_service,
    register_pipeline,
    rollback,
    set_pipeline_config,
    watch_prs,
)

from .conftest import FakeHTTPClient, FakeResponse, requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


def _patch_github(monkeypatch, responses: dict) -> None:
    monkeypatch.setattr(PT.httpx, "Client", lambda *a, **k: FakeHTTPClient(responses))


# ── básicos ───────────────────────────────────────────────────────────────────
async def test_register_get_list(store_a):
    reg = await register_pipeline(store_a, "svc", "o/svc")
    assert reg["action"] == "created"
    got = await get_pipeline(store_a, "svc")
    assert got["service"] == "svc"
    assert (await get_pipeline(store_a, "absent"))["error"] == "not_found"
    listed = await list_pipeline(store_a)
    assert listed["total"] == 1


# ── promote_service ───────────────────────────────────────────────────────────
async def test_promote_blocked_and_mismatch(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await block_service(store_a, "svc", "risco", "ops")
    r = await promote_service(store_a, "svc", "dev", "homol", "u")
    assert r["error"] == "service_blocked"

    await register_pipeline(store_a, "svc2", "o/svc2")
    r2 = await promote_service(store_a, "svc2", "homol", "prod", "u")  # está em dev
    assert r2["error"] == "env_mismatch"


async def test_promote_gates_fail(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": ["qa_tests"]})
    r = await promote_service(store_a, "svc", "dev", "homol", "u")
    assert r["can_promote"] is False
    assert "qa_tests" in r["failed_gates"]


async def test_promote_creates_pr(store_a, monkeypatch):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": ["qa_tests"]})
    from src.tools import add_gate_result

    await add_gate_result(store_a, "svc", "dev", "qa_tests", True)  # gate lido do from_env
    _patch_github(monkeypatch, {"POST": FakeResponse(201, {"number": 42, "html_url": "http://pr/42"})})
    r = await promote_service(
        store_a, "svc", "dev", "homol", "u", "motivo", github_token="ghp", github_org="o"
    )
    assert r["promoted"] is True
    assert r["status"] == "waiting_approval"
    assert r["pr_number"] == 42


async def test_promote_github_unavailable_is_pending(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    await set_pipeline_config(store_a, "svc", {"homol": []})  # sem gates exigidos
    r = await promote_service(store_a, "svc", "dev", "homol", "u")  # sem token → unavailable
    assert r["promoted"] is True
    assert r["status"] == "pending"


# ── approve_promotion ─────────────────────────────────────────────────────────
async def test_approve_not_found_and_invalid_status(store_a):
    assert (await approve_promotion(store_a, 999, "a"))["error"] == "not_found"
    await register_pipeline(store_a, "svc", "o/svc")
    pid = await store_a.add_promotion("svc", "dev", "homol", "u", None, {}, "homol", "approved")
    assert (await approve_promotion(store_a, pid, "a"))["error"] == "invalid_status"


async def test_approve_merges_pr(store_a, monkeypatch):
    await register_pipeline(store_a, "svc", "o/svc")
    pid = await store_a.add_promotion(
        "svc", "dev", "homol", "u", None, {}, "homol", "waiting_approval", pr_number=7
    )
    _patch_github(monkeypatch, {"PUT": FakeResponse(200, {"sha": "abc123", "message": "Merged"})})
    r = await approve_promotion(store_a, pid, "boss", github_token="ghp", github_org="o")
    assert r["approved"] is True
    assert r["merge_sha"] == "abc123"
    # ambiente promovido
    assert (await get_pipeline(store_a, "svc"))["current_env"] == "homol"


# ── watch_prs ─────────────────────────────────────────────────────────────────
async def test_watch_prs_not_configured(store_a):
    assert (await watch_prs(store_a))["error"] == "github_not_configured"


async def test_watch_prs_auto_and_human(store_a, monkeypatch):
    await register_pipeline(store_a, "svc", "o/svc")
    prs = [
        {
            "number": 1,
            "title": "feat",
            "html_url": "u1",
            "base": {"ref": "develop"},
            "head": {"ref": "f1"},
            "user": {"login": "dev"},
            "created_at": "t",
        },
        {
            "number": 2,
            "title": "rel",
            "html_url": "u2",
            "base": {"ref": "homol"},
            "head": {"ref": "develop"},
            "user": {"login": "dev"},
            "created_at": "t",
        },
    ]
    _patch_github(monkeypatch, {"GET": FakeResponse(200, prs), "PUT": FakeResponse(200, {"sha": "s"})})
    r = await watch_prs(store_a, github_token="ghp", github_org="o", repos=["o/svc"])
    assert r["auto_approved_count"] == 1  # develop
    assert r["waiting_human_count"] == 1  # homol


# ── rollback / history / overview ─────────────────────────────────────────────
async def test_rollback(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    r = await rollback(store_a, "svc", "prod", "v1", "ops", "motivo")
    assert r["rolled_back"] is True
    assert (await rollback(store_a, "absent", "prod", "v1", "ops"))["error"] == "not_found"


async def test_history_and_overview(store_a):
    await register_pipeline(store_a, "svc", "o/svc")
    hist = await get_promotion_history(store_a)
    assert hist["limit"] == 20
    ov = await get_pipeline_overview(store_a)
    assert ov["total_services"] == 1
    assert (await set_pipeline_config(store_a, "absent", {}))["error"] == "not_found"
    assert (await block_service(store_a, "absent", "r", "a"))["error"] == "not_found"
