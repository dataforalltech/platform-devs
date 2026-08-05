# Portado de `audit-mcp-server/tests/test_tools.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Tools herméticos do audit-mcp (sem DB): policy/checklist leem YAML do repo e
run_audit nos caminhos que retornam ANTES de tocar o store (repo irresolúvel /
erro interno) + validação de criticidade. Nenhum toca MySQL — `store=None`."""

from __future__ import annotations

from src.domains.audit.tools.audit_tool import run_audit
from src.domains.audit.tools.checklist_tool import get_compliance_checklist
from src.domains.audit.tools.policy_tool import get_compliance_policy, set_service_criticality


# ── get_compliance_policy ─────────────────────────────────────────────────────
async def test_get_compliance_policy_dev(settings):
    result = await get_compliance_policy(None, settings, env="dev")
    assert result["env"] == "dev"
    assert result["min_score"] == 0.5
    assert "required_checkers" in result


async def test_get_compliance_policy_hml(settings):
    result = await get_compliance_policy(None, settings, env="hml")
    assert result["env"] == "hml"
    assert result["min_score"] == 0.7


async def test_get_compliance_policy_prod(settings):
    result = await get_compliance_policy(None, settings, env="prod")
    assert result["env"] == "prod"
    assert result["min_score"] == 0.85


async def test_get_compliance_policy_not_found(settings):
    result = await get_compliance_policy(None, settings, env="staging")
    assert result["error"] == "NotFound"
    assert result["tool"] == "get_compliance_policy"


# ── get_compliance_checklist ──────────────────────────────────────────────────
async def test_get_compliance_checklist(settings):
    result = await get_compliance_checklist(None, settings, service="svc", repo="r", env="dev")
    assert result["service"] == "svc"
    assert result["env"] == "dev"
    assert result["min_score"] == 0.5
    assert result["checklist_items"] == len(result["checklist"])
    assert result["checklist_items"] > 0
    assert any(i["required"] and i["name"] == "has_src_dir" for i in result["checklist"])
    assert any(not i["required"] for i in result["checklist"])


async def test_get_compliance_checklist_not_found(settings):
    result = await get_compliance_checklist(None, settings, service="svc", repo="r", env="staging")
    assert result["error"] == "NotFound"


# ── set_service_criticality — validação (retorna antes do store) ──────────────
async def test_set_service_criticality_invalid(settings):
    result = await set_service_criticality(
        None, settings, service="svc", criticality="invalid", updated_by="admin"
    )
    assert result["error"] == "ValidationError"
    assert result["tool"] == "set_service_criticality"


# ── run_audit — caminhos pré-store ────────────────────────────────────────────
async def test_run_audit_repo_not_resolvable(settings):
    """Sem repo_path válido, run_audit falha com ValidationError antes de tocar o DB."""
    result = await run_audit(None, settings, service="svc", repo="ghost-repo", env="dev")
    assert result["error"] == "ValidationError"
    assert result["tool"] == "run_audit"


async def test_run_audit_internal_error(settings, monkeypatch):
    """Exceção inesperada (na resolução) é capturada como InternalError, antes do DB."""

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("src.domains.audit.tools.audit_tool.RepoResolver", boom)
    result = await run_audit(None, settings, service="s", repo="r", env="dev")
    assert result["error"] == "InternalError"
    assert "kaboom" in result["details"]
