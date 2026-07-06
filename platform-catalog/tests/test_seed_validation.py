"""Review adversarial do seed — o checklist de 7 pontos como invariantes enforçadas.

Se o seed regredir (write perigoso vira low, high sem N2, read não-idempotente, merge
indevido, id ilegível, binding órfão, query de produção vazia), estes testes FALHAM.
"""

from __future__ import annotations

import pytest

from platform_catalog.derive import derive_operation
from platform_catalog.registry import CatalogStore
from platform_catalog.validate import DANGEROUS_EFFECTS, ID_RE, validate_catalog

# merges legítimos conhecidos (mesmo domínio + mesmo nome de tool em providers distintos).
# Um merge NOVO fora desta lista deve falhar o teste e exigir revisão humana (§4).
EXPECTED_MULTIBINDING = {
    "infra.set_env_var", "infra.list_environments", "infra.read_env_file",
    "infra.audit_env_files", "infra.redact_env_secrets", "development.status",
    "product.generate_feature_spec", "product.generate_go_to_market_brief",
    "product.define_product_vision", "product.generate_release_plan",
}


@pytest.fixture(scope="module")
def store():
    return CatalogStore().load()


def test_gate_zero_violations(store):
    """O gate completo (§1-§7) roda limpo."""
    assert validate_catalog(store) == []


# §1 — nenhum write perigoso classificado como low/medium
def test_no_dangerous_write_underclassified(store):
    for o in store.operations.values():
        s = o["spec"]
        eff = set(s["risk"]["effects"])
        if s["authz"] == "write":
            assert s["risk"]["default_level"] != "low", o["metadata"]["uid"]
        if eff & DANGEROUS_EFFECTS:
            assert s["risk"]["default_level"] in ("high", "critical"), o["metadata"]["uid"]


# §2 — todo high/critical exige N2
def test_all_high_require_n2(store):
    for o in store.operations.values():
        if o["spec"]["risk"]["default_level"] in ("high", "critical"):
            assert o["spec"]["risk"]["approval_required"] == "N2", o["metadata"]["uid"]


# §3 — toda read é idempotente
def test_all_reads_idempotent(store):
    for o in store.operations.values():
        if o["spec"]["authz"] == "read":
            assert o["spec"]["contract"]["execution"]["idempotent"] is True, o["metadata"]["uid"]


# §4 — multi-binding não colapsou operações diferentes
def test_multibinding_is_expected_and_distinct(store):
    multi = {op: store.list_tools_for(op) for op in
             {t["spec"]["operation_id"] for t in store.tools}
             if len(store.list_tools_for(op)) > 1}
    assert set(multi) == EXPECTED_MULTIBINDING            # nenhum merge inesperado
    for op, tools in multi.items():
        provs = [t["spec"]["provider_id"] for t in tools]
        assert len(provs) == len(set(provs)), f"provider duplicado em {op}"


# §5 — Operation IDs estáveis e legíveis
def test_ids_readable_unique_and_stable(store):
    uids = list(store.operations)
    assert len(uids) == len(set(uids))                    # únicos
    for uid in uids:
        assert ID_RE.match(uid), uid                       # legível
    # estabilidade: re-derivar dá o mesmo id (determinístico)
    assert derive_operation("deploy-mcp-server", "deploy", "write")[0] == "delivery.deploy"


# §6 — rastreabilidade até a tool original
def test_traceability_operation_to_provider_tool(store):
    for uid in store.operations:
        tools = store.list_tools_for(uid)
        assert tools, f"operation sem binding: {uid}"
        for t in tools:
            assert t["spec"]["provider_id"] and t["spec"]["tool"]
    # e volta: um binding conhecido aponta pro provider/tool originais
    dep = [t for t in store.list_tools_for("delivery.deploy")]
    assert any(t["spec"]["provider_id"] == "deploy-mcp" and t["spec"]["tool"] == "deploy"
               for t in dep)


# §7 — "quem pode impactar produção?"
def test_production_impact_query(store):
    prod = store.find_production_impacting()
    assert prod, "query de impacto-produção vazia"
    ids = {o["metadata"]["uid"] for o in prod}
    assert "delivery.deploy" in ids and "delivery.rollback" in ids
    assert all(o["spec"]["authz"] == "write" for o in prod)      # impacto real = write
    # rastreável: quem implementa o deploy?
    assert store.providers_for("delivery.deploy") == ["deploy-mcp"]
