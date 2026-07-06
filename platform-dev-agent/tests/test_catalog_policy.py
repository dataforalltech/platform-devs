"""Fase 2 — resolver registry-backed + PDP por recurso/efeito."""

from __future__ import annotations

from app.dev_agent.catalog import (
    CapabilityRecord, DirCatalogSource, InMemoryCatalogSource, PolicyEngine,
    RegistryCapabilityResolver,
)
from app.dev_agent.models.plan import Capability, RiskLevel

DEPLOY = CapabilityRecord(
    tool="deploy-mcp.deploy", operation_id="delivery.deploy", domain="delivery",
    capability="write", risk_level="high", effects=("deploy",),
    blast_radius="environment", approval_required="N2", resource="deployment")
READ = CapabilityRecord(
    tool="services-mcp.list_services", operation_id="infra.list_services", domain="infra",
    capability="read", risk_level="low", effects=("read",),
    blast_radius="none", approval_required="none", resource="service")
WRITE_ENV = CapabilityRecord(  # write cujo blast excede 'service'
    tool="x-mcp.mutate", operation_id="infra.mutate", domain="infra", capability="write",
    risk_level="high", effects=("write",), blast_radius="environment", resource="service")


# --- resolver registry-backed -----------------------------------------------
def test_resolver_prefers_catalog():
    r = RegistryCapabilityResolver(InMemoryCatalogSource({DEPLOY.tool: DEPLOY}))
    assert r.resolve("deploy-mcp.deploy") is Capability.WRITE
    assert r.classify_risk("deploy-mcp.deploy", Capability.WRITE) is RiskLevel.HIGH
    assert r.record("deploy-mcp.deploy").approval_required == "N2"


def test_resolver_falls_back_to_heuristic():
    r = RegistryCapabilityResolver(InMemoryCatalogSource({}))   # catálogo vazio
    # heurística: prefixo create_ => WRITE
    assert r.resolve("foo-mcp.create_bar") is Capability.WRITE
    assert r.resolve("foo-mcp.get_bar") is Capability.READ


# --- PDP por recurso/efeito (deny-by-default) --------------------------------
def test_read_only_persona_denied_deploy_effect():
    d = PolicyEngine().decide(profile="security", record=DEPLOY)
    assert not d and "effect" in d.reason


def test_write_persona_denied_when_blast_exceeds_ceiling():
    d = PolicyEngine().decide(profile="backend", record=WRITE_ENV)
    assert not d and "blast_radius" in d.reason


def test_devops_allowed_deploy_with_n2():
    d = PolicyEngine().decide(profile="devops", record=DEPLOY)
    assert d and d.approval_required == "N2"


def test_read_op_allowed_for_read_persona():
    assert PolicyEngine().decide(profile="qa_engineer", record=READ)


def test_unknown_profile_is_minimal_read_only():
    assert not PolicyEngine().decide(profile="stranger", record=DEPLOY)
    assert PolicyEngine().decide(profile="stranger", record=READ)


# --- integração: lê o catálogo REAL da Fase 1 (platform-catalog/catalog) ------
def test_dir_source_reads_real_fase1_catalog():
    src = DirCatalogSource()
    dep = src.record("deploy-mcp.deploy")
    assert dep is not None, "catálogo da Fase 1 não encontrado (rode generate_seed)"
    assert dep.capability == "write" and dep.risk_level == "high"
    assert "deploy" in dep.effects and dep.blast_radius == "environment"
    assert dep.approval_required == "N2"
    rd = src.record("services-mcp.list_services")
    assert rd is not None and rd.capability == "read" and rd.risk_level == "low"


def test_end_to_end_resolver_plus_policy_on_real_catalog():
    """Cadeia Fase-1→Fase-2: resolver lê o catálogo real e o PDP decide por efeito."""
    r = RegistryCapabilityResolver(DirCatalogSource())
    rec = r.record("deploy-mcp.deploy")
    assert rec is not None
    pdp = PolicyEngine()
    assert not pdp.decide(profile="qa_engineer", record=rec)   # QA não faz deploy
    assert pdp.decide(profile="devops", record=rec)            # devops faz, com N2
