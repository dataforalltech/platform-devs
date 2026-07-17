"""Tools de proposta de arquitetura — persistem a proposta derivada dos inputs.

O antigo `generate_architecture` (escolha de estilo arquitetural por heurísticas de
palavra-chave transparentes + táticas por atributo de qualidade) foi **preservado**
como `build_architecture_proposal` (função pura) e **dobrado** em
`save_architecture_blueprint`: o agente fornece domínio/restrições/atributos, o builder
deriva a proposta estruturada (com `triggered_by` rastreável) e a tool a persiste como
histórico. Thin wrappers sobre o `ArchitectureStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ArchitectureStore
from ._common import as_str_list, match_hints

# Heurísticas transparentes: palavra-chave → estilo arquitetural sugerido.
_STYLE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("Event-Driven Microservices", ("event", "evento", "stream", "kafka", "assíncron", "async")),
    (
        "Microservices",
        ("microservi", "scal", "escal", "independent", "decoupl", "desacopl", "distributed", "distribuíd"),
    ),
    ("Serverless", ("serverless", "lambda", "function", "faas", "pay-per-use", "sob demanda")),
    ("Modular Monolith", ("monolith", "monólito", "single deploy", "startup", "mvp", "simple", "simples")),
    ("Layered (N-Tier)", ("crud", "traditional", "tradicional")),
]

# Palavra-chave → tática por atributo de qualidade.
_QA_TACTICS = {
    "scalability": "Escalonamento horizontal + statelessness nos serviços",
    "escalabilidade": "Escalonamento horizontal + statelessness nos serviços",
    "latency": "Cache e leituras replicadas próximas do consumidor",
    "latência": "Cache e leituras replicadas próximas do consumidor",
    "availability": "Redundância multi-AZ + health checks + failover",
    "disponibilidade": "Redundância multi-AZ + health checks + failover",
    "security": "AuthN/AuthZ centralizado, criptografia em trânsito e repouso",
    "segurança": "AuthN/AuthZ centralizado, criptografia em trânsito e repouso",
    "observability": "Logs estruturados, métricas e tracing distribuído",
    "observabilidade": "Logs estruturados, métricas e tracing distribuído",
}


def build_architecture_proposal(
    domain: str = "",
    constraints: list[Any] | None = None,
    quality_attributes: list[Any] | None = None,
    architecture_name: str = "",
) -> dict[str, Any]:
    """Deriva uma proposta de arquitetura (estilo + táticas) dos inputs.

    Determinístico: o estilo sai de heurísticas de palavra-chave transparentes
    (``rationale.triggered_by``); as táticas mapeiam os atributos de qualidade. Não é
    raciocínio arquitetural generativo — é um scaffold estruturado rastreável."""
    domain = (domain or "").strip()
    constraint_list = as_str_list(constraints)
    qa_list = as_str_list(quality_attributes)
    name = (architecture_name or "").strip() or (
        f"{domain} architecture".strip() if domain else "Architecture"
    )
    combined = f"{domain}\n{' '.join(constraint_list)}\n{' '.join(qa_list)}".strip()

    style_matches = match_hints(combined, _STYLE_HINTS)
    if style_matches:
        chosen = style_matches[0]
        alternatives = [m["name"] for m in style_matches[1:]]
        rationale = {"style": chosen["name"], "triggered_by": chosen["triggered_by"]}
    else:
        rationale = {
            "style": "Modular Monolith",
            "triggered_by": [],
            "note": "default — nenhum sinal específico detectado; opção de menor custo inicial",
        }
        alternatives = ["Microservices"]

    tactics = []
    for qa in qa_list:
        tactic = _QA_TACTICS.get(qa.strip().lower())
        tactics.append(
            {
                "quality_attribute": qa,
                "tactic": tactic or "Definir tática específica (não coberta por heurística)",
                "heuristic_matched": tactic is not None,
            }
        )

    return {
        "title": f"Architecture Proposal — {name}",
        "name": name,
        "domain": domain,
        "constraints": constraint_list,
        "quality_attributes": qa_list,
        "proposed_style": rationale["style"],
        "rationale": rationale,
        "alternatives_considered": alternatives,
        "tactics": tactics,
    }


async def save_architecture_blueprint(
    store: ArchitectureStore,
    domain: str,
    constraints: Any = None,
    quality_attributes: Any = None,
    architecture_name: str = "",
    status: str | None = None,
) -> dict[str, Any]:
    """Deriva a proposta dos inputs e a persiste (histórico)."""
    proposal = build_architecture_proposal(
        domain=domain,
        constraints=constraints,
        quality_attributes=quality_attributes,
        architecture_name=architecture_name,
    )
    blueprint = await store.save_architecture_blueprint(
        name=proposal["name"],
        domain=proposal["domain"] or domain,
        style=proposal["proposed_style"],
        constraints=proposal["constraints"],
        quality_attributes=proposal["quality_attributes"],
        content=proposal,
        status=status,
    )
    return {"saved": True, "architecture_blueprint": blueprint}


async def list_architecture_blueprints(
    store: ArchitectureStore, domain: str | None = None, status: str | None = None
) -> dict[str, Any]:
    blueprints = await store.list_architecture_blueprints(domain=domain, status=status)
    return {
        "total": len(blueprints),
        "filters": {"domain": domain, "status": status},
        "architecture_blueprints": blueprints,
    }


async def get_architecture_blueprint(store: ArchitectureStore, blueprint_id: int) -> dict[str, Any]:
    blueprint = await store.get_architecture_blueprint(blueprint_id)
    if blueprint is None:
        return {"error": "not_found", "id": blueprint_id}
    return blueprint


async def update_architecture_blueprint(
    store: ArchitectureStore,
    blueprint_id: int,
    name: str | None = None,
    style: str | None = None,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    blueprint = await store.update_architecture_blueprint(
        blueprint_id, name=name, style=style, content=content, status=status
    )
    if blueprint is None:
        return {"error": "not_found", "id": blueprint_id}
    return {"updated": True, "architecture_blueprint": blueprint}


async def delete_architecture_blueprint(store: ArchitectureStore, blueprint_id: int) -> dict[str, Any]:
    deleted = await store.delete_architecture_blueprint(blueprint_id)
    return {"deleted": deleted > 0, "id": blueprint_id, "deleted_count": deleted}
