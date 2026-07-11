"""AuditStore + get_audit_log tool contra MySQL real (§16 / FID-02).

record (append), query (filtros repo/risk_level/approved + paginação), stats agregado,
store vazio e ISOLAMENTO por tenant. Store nunca mockado.
"""

from __future__ import annotations

import pytest

from src.tools.audit_tool import get_audit_log

from .conftest import requires_mysql

pytestmark = [pytest.mark.integration, requires_mysql]


def _make_result(
    *,
    repo: str = "platform-test",
    task: str = "Tarefa de teste",
    approved: bool = True,
    risk: str = "low",
    violations: list[str] | None = None,
    required_actions: list[str] | None = None,
    layers: list[str] | None = None,
    files_count: int = 3,
) -> dict:
    """Constrói um resultado sintético de validate_agent_decision."""
    return {
        "approved": approved,
        "risk_level": risk,
        "violations": violations or [],
        "required_actions": required_actions or [],
        "recommendations": [],
        "notes": [],
        "input_summary": {
            "repository_name": repo,
            "task_description": task,
            "affected_files_count": files_count,
            "affected_layers": layers or ["backend"],
            "changes_contracts": False,
            "adds_fallback": False,
            "adds_dependency": False,
            "modifies_security": False,
        },
    }


async def _populate(audit, n: int = 10) -> None:
    for i in range(n):
        repo = "platform-auth" if i % 2 == 0 else "platform-ml"
        risk = "critical" if i % 3 == 0 else ("high" if i % 3 == 1 else "low")
        approved = risk != "critical"
        result = _make_result(repo=repo, risk=risk, approved=approved)
        await audit.record(result, result["input_summary"])


# ── AuditStore.record ─────────────────────────────────────────────────────────
async def test_record_grava_e_recupera(stores_a):
    _, audit = stores_a
    result = _make_result(repo="platform-auth", risk="medium")
    await audit.record(result, result["input_summary"])
    entries = await audit.query(limit=100)
    assert len(entries) == 1
    assert entries[0]["repo"] == "platform-auth"
    assert entries[0]["risk_level"] == "medium"


async def test_record_acumula_multiplas(stores_a):
    _, audit = stores_a
    for i in range(5):
        result = _make_result(repo=f"repo-{i}")
        await audit.record(result, result["input_summary"])
    assert len(await audit.query(limit=100)) == 5


async def test_record_campos_obrigatorios(stores_a):
    _, audit = stores_a
    result = _make_result(
        approved=False,
        risk="critical",
        violations=["Fallback silencioso detectado."],
        required_actions=["Remover o fallback."],
    )
    await audit.record(result, result["input_summary"])
    entry = (await audit.query(limit=1))[0]
    required = {
        "ts",
        "repo",
        "task_description",
        "approved",
        "risk_level",
        "violations_count",
        "violations",
        "required_actions_count",
        "required_actions",
        "affected_layers",
        "affected_files_count",
        "flags",
    }
    assert required.issubset(entry.keys())
    assert entry["approved"] is False
    assert entry["violations_count"] == 1
    assert entry["violations"] == ["Fallback silencioso detectado."]


async def test_record_trunca_task_description(stores_a):
    _, audit = stores_a
    result = _make_result(task="x" * 500)
    await audit.record(result, result["input_summary"])
    entry = (await audit.query(limit=1))[0]
    assert len(entry["task_description"]) == 200


async def test_record_input_summary_embutido(stores_a):
    _, audit = stores_a
    result = _make_result(repo="platform-ml")
    await audit.record(result)  # sem input_summary explícito → lê de result["input_summary"]
    entry = (await audit.query(limit=1))[0]
    assert entry["repo"] == "platform-ml"


async def test_record_flags(stores_a):
    _, audit = stores_a
    result = _make_result()
    result["input_summary"]["changes_contracts"] = True
    result["input_summary"]["adds_dependency"] = True
    await audit.record(result, result["input_summary"])
    entry = (await audit.query(limit=1))[0]
    assert entry["flags"]["changes_contracts"] is True
    assert entry["flags"]["adds_dependency"] is True


# ── AuditStore.query ──────────────────────────────────────────────────────────
async def test_query_vazio(stores_a):
    _, audit = stores_a
    assert await audit.query() == []


async def test_query_ordem_cronologica_reversa(stores_a):
    _, audit = stores_a
    for repo in ["a", "b", "c"]:
        r = _make_result(repo=repo)
        await audit.record(r, r["input_summary"])
    entries = await audit.query(limit=10)
    assert entries[0]["repo"] == "c"  # mais recente primeiro
    assert entries[-1]["repo"] == "a"


async def test_query_filtro_repo_substring(stores_a):
    _, audit = stores_a
    await _populate(audit, 10)
    entries = await audit.query(repo="platform-auth", limit=100)
    assert entries and all("platform-auth" in e["repo"] for e in entries)


async def test_query_filtro_risk_level(stores_a):
    _, audit = stores_a
    await _populate(audit, 9)
    entries = await audit.query(risk_level="critical", limit=100)
    assert entries and all(e["risk_level"] == "critical" for e in entries)


async def test_query_filtro_approved(stores_a):
    _, audit = stores_a
    await _populate(audit, 9)
    assert all(e["approved"] is False for e in await audit.query(approved=False, limit=100))
    assert all(e["approved"] is True for e in await audit.query(approved=True, limit=100))


async def test_query_paginacao(stores_a):
    _, audit = stores_a
    await _populate(audit, 10)
    full = await audit.query(limit=100, offset=0)
    page1 = await audit.query(limit=5, offset=0)
    page2 = await audit.query(limit=5, offset=5)
    assert len(page1) + len(page2) == 10
    assert page1 + page2 == full


async def test_query_limit_clamp_500(stores_a):
    _, audit = stores_a
    for _ in range(10):
        r = _make_result()
        await audit.record(r, r["input_summary"])
    assert len(await audit.query(limit=600)) == 10  # clamp p/ 500; só há 10


# ── AuditStore.stats ──────────────────────────────────────────────────────────
async def test_stats_vazio(stores_a):
    _, audit = stores_a
    s = await audit.stats()
    assert s["total"] == 0
    assert s["approved"] == 0
    assert s["blocked"] == 0


async def test_stats_contagens_e_block_rate(stores_a):
    _, audit = stores_a
    for _ in range(3):
        r = _make_result(approved=True)
        await audit.record(r, r["input_summary"])
    r = _make_result(approved=False, risk="critical")
    await audit.record(r, r["input_summary"])
    s = await audit.stats()
    assert s["total"] == 4
    assert s["approved"] == 3
    assert s["blocked"] == 1
    assert s["block_rate"] == pytest.approx(0.25, rel=1e-3)


async def test_stats_by_risk_e_top_repos(stores_a):
    _, audit = stores_a
    for risk in ["low", "low", "high", "critical"]:
        r = _make_result(approved=risk != "critical", risk=risk, repo="platform-auth")
        await audit.record(r, r["input_summary"])
    r = _make_result(repo="platform-ml")
    await audit.record(r, r["input_summary"])
    s = await audit.stats()
    assert s["by_risk_level"].get("low", 0) == 2
    assert s["by_risk_level"].get("critical", 0) == 1
    repos = {item["repo"]: item["count"] for item in s["top_repos"]}
    assert repos["platform-auth"] == 4
    assert repos["platform-ml"] == 1


# ── get_audit_log tool ────────────────────────────────────────────────────────
async def test_tool_modo_lista(stores_a):
    _, audit = stores_a
    for i in range(5):
        r = _make_result(repo=f"repo-{i}")
        await audit.record(r, r["input_summary"])
    result = await get_audit_log(audit)
    assert "entries" in result
    assert result["count"] == 5


async def test_tool_modo_stats(stores_a):
    _, audit = stores_a
    r = _make_result(approved=False, risk="critical")
    await audit.record(r, r["input_summary"])
    result = await get_audit_log(audit, query="stats")
    assert result["stats"]["total"] == 1
    assert result["stats"]["blocked"] == 1


async def test_tool_filtro_repo(stores_a):
    _, audit = stores_a
    for name in ["platform-auth", "platform-ml", "platform-auth"]:
        r = _make_result(repo=name)
        await audit.record(r, r["input_summary"])
    result = await get_audit_log(audit, filter_repo="platform-auth", limit=100)
    assert result["count"] == 2
    assert all("platform-auth" in e["repo"] for e in result["entries"])


async def test_tool_filtro_risk_e_approved(stores_a):
    _, audit = stores_a
    r1 = _make_result(risk="low")
    await audit.record(r1, r1["input_summary"])
    r2 = _make_result(approved=False, risk="critical")
    await audit.record(r2, r2["input_summary"])
    by_risk = await get_audit_log(audit, risk_level="critical", limit=100)
    assert by_risk["count"] == 1
    assert by_risk["entries"][0]["risk_level"] == "critical"
    by_approved = await get_audit_log(audit, approved=False, limit=100)
    assert by_approved["count"] == 1
    assert by_approved["entries"][0]["approved"] is False


async def test_tool_paginacao(stores_a):
    _, audit = stores_a
    for i in range(10):
        r = _make_result(repo=f"repo-{i}")
        await audit.record(r, r["input_summary"])
    full = await get_audit_log(audit, limit=100, offset=0)
    page1 = await get_audit_log(audit, limit=5, offset=0)
    page2 = await get_audit_log(audit, limit=5, offset=5)
    assert page1["count"] == 5 and page2["count"] == 5
    assert page1["entries"] + page2["entries"] == full["entries"]


async def test_tool_store_vazio(stores_a):
    _, audit = stores_a
    result = await get_audit_log(audit)
    assert result["entries"] == []
    assert result["count"] == 0
    stats = await get_audit_log(audit, query="stats")
    assert stats["stats"]["total"] == 0


# ── Isolamento por tenant ─────────────────────────────────────────────────────
async def test_tenant_isolation(stores_a, stores_b):
    _, audit_a = stores_a
    _, audit_b = stores_b
    r = _make_result(repo="only-in-a")
    await audit_a.record(r, r["input_summary"])
    assert len(await audit_a.query(limit=100)) == 1
    assert await audit_b.query(limit=100) == []
