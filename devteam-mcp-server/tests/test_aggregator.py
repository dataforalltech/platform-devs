"""Testes do server AGREGADOR (devteam-mcp) — registro + roteamento, SEM banco.

Cobre o contrato do agregador que os 19 domínios restantes vão replicar:
  * o ``_TOOL_SCHEMAS`` é o merge dos schemas de todos os domínios, com as chaves
    PREFIXADAS pelo domínio (``architecture_<op>``) — sem colisão entre domínios;
  * cada tool carrega os 4 campos de policy (capability/required_scope/resource_type/
    data_domain) com os valores esperados p/ o domínio consolidado;
  * o ``_dispatch`` descobre o domínio pelo prefixo (``name.split("_", 1)[0]``) e roteia
    para o handler certo — provado com um gerador (compute puro) e um caminho de
    validação que retorna ANTES de qualquer I/O de banco (Store mockada).

Nada aqui abre conexão: o import do agregador e o registro são puros; o dispatch usa uma
sessão/Store falsa (``MagicMock``) e só exercita caminhos que não persistem.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.server import mcp_server as M

# As 18 tools do domínio-piloto architecture, já prefixadas no agregador.
_EXPECTED_ARCHITECTURE_TOOLS = {
    "architecture_save_architecture_blueprint",
    "architecture_list_architecture_blueprints",
    "architecture_get_architecture_blueprint",
    "architecture_update_architecture_blueprint",
    "architecture_delete_architecture_blueprint",
    "architecture_set_c4_diagram",
    "architecture_list_c4_diagrams",
    "architecture_get_c4_diagram",
    "architecture_delete_c4_diagram",
    "architecture_save_solution_blueprint",
    "architecture_list_solution_blueprints",
    "architecture_get_solution_blueprint",
    "architecture_update_solution_blueprint",
    "architecture_delete_solution_blueprint",
    "architecture_save_artifact",
    "architecture_list_artifacts",
    "architecture_get_artifact",
    "architecture_delete_artifact",
    "architecture_generate_c4_diagram",
    "architecture_generate_sequence_diagram",
    "architecture_generate_adr",
}


def _domain_of(name: str) -> str | None:
    """Descobre o domínio de uma tool por longest-prefix (igual ao agregador)."""
    matched = [k for k in M._DOMAINS_BY_KEY if name.startswith(f"{k}_")]
    return max(matched, key=len) if matched else None


# ── Registro / merge de schemas ───────────────────────────────────────────────
def test_aggregator_merges_all_domains():
    # architecture (piloto) continua presente, prefixado.
    assert _EXPECTED_ARCHITECTURE_TOOLS <= set(M._TOOL_SCHEMAS)
    # _TOOL_SCHEMAS = união EXATA dos schemas de todos os domínios (sem perda/colisão):
    # como as chaves já vêm prefixadas <domain>_, a soma dos tamanhos == tamanho do merge.
    expected_total = sum(len(d["schemas"]) for d in M.DOMAINS)
    assert len(M._TOOL_SCHEMAS) == expected_total
    # todo domínio registrado contribuiu ao menos uma tool (nenhum pacote silenciosamente pulado).
    for d in M.DOMAINS:
        assert any(_domain_of(name) == d["name"] for name in M._TOOL_SCHEMAS), d["name"]


def test_reference_tools_present_with_prefix():
    # As tools de referência citadas no design existem, PREFIXADAS pelo domínio.
    assert "architecture_save_artifact" in M._TOOL_SCHEMAS
    assert "architecture_get_c4_diagram" in M._TOOL_SCHEMAS
    # Os nomes de op sem prefixo NÃO são chaves do agregador (evita colisão entre domínios).
    assert "save_artifact" not in M._TOOL_SCHEMAS
    assert "get_c4_diagram" not in M._TOOL_SCHEMAS


def test_every_tool_is_domain_prefixed():
    # Toda chave casa com um domínio registrado por ``name.split("_", 1)[0]``.
    domain_keys = set(M._DOMAINS_BY_KEY)
    for name in M._TOOL_SCHEMAS:
        assert name.split("_", 1)[0] in domain_keys, f"{name}: prefixo sem domínio registrado"


def test_policy_metadata_shape():
    # Invariantes de policy VÁLIDAS p/ TODOS os 20 domínios (não só architecture).
    for name, meta in M._TOOL_SCHEMAS.items():
        dom = _domain_of(name)
        assert dom, f"{name}: prefixo sem domínio registrado"
        # capability estável = <namespace consolidado>.<tool prefixado>
        assert meta["capability"] == f"devteam-mcp.{name}"
        # required_scope preserva o least-privilege por-tool, domínio-scoped (não devteam):
        # <domain>:<resource_type>:<ação> → começa pelo domínio e tem exatamente 2 ":".
        assert meta["required_scope"].startswith(f"{dom}:"), (name, meta["required_scope"])
        assert meta["required_scope"].count(":") == 2, (name, meta["required_scope"])
        # data_domain/resource_type mantêm os valores originais do domínio (não-vazios).
        assert meta["data_domain"], name
        assert meta["resource_type"], name
        # inputSchema MUST ser type=object; required ⊆ properties.
        schema = meta["schema"]
        assert schema["type"] == "object", name
        props = set(schema.get("properties", {}))
        assert set(schema.get("required", [])) <= props, name


def test_specific_capability_and_scope_values():
    save = M._TOOL_SCHEMAS["architecture_save_artifact"]
    assert save["capability"] == "devteam-mcp.architecture_save_artifact"
    assert save["required_scope"] == "architecture:artifact:write"
    assert save["resource_type"] == "artifact"
    c4 = M._TOOL_SCHEMAS["architecture_get_c4_diagram"]
    assert c4["capability"] == "devteam-mcp.architecture_get_c4_diagram"
    assert c4["required_scope"] == "architecture:c4_diagram:read"


# ── Roteamento do _dispatch (Store/sessão mockada — sem banco) ────────────────
async def test_dispatch_routes_generator_to_architecture_handler():
    # Gerador = compute puro: roteia p/ o handler do architecture e IGNORA a store.
    out = await M._dispatch("architecture_generate_adr", {"title": "Escolher a fila"}, MagicMock())
    assert out["kind"] == "adr"

    c4 = await M._dispatch(
        "architecture_generate_c4_diagram", {"level": "context", "elements": ["S"]}, MagicMock()
    )
    assert c4["kind"] == "c4_diagram"


async def test_dispatch_routes_store_tool_validation_path():
    # save_artifact valida ``kind`` ANTES de tocar a store → prova o roteamento sem I/O.
    out = await M._dispatch(
        "architecture_save_artifact", {"kind": "nope", "target": "x", "content": "c"}, MagicMock()
    )
    assert out["error"] == "invalid_kind"


async def test_dispatch_unknown_op_in_known_domain_raises_keyerror():
    with pytest.raises(KeyError):
        await M._dispatch("architecture_does_not_exist", {}, MagicMock())


async def test_dispatch_unknown_domain_raises_keyerror():
    with pytest.raises(KeyError):
        await M._dispatch("bogus_tool", {}, MagicMock())
