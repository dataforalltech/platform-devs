"""Tools de blueprint de solução — persistem o blueprint derivado dos requisitos.

O antigo `generate_solution_blueprint` (derivação de camadas/componentes + sugestão de
padrões/NFRs por heurísticas de palavra-chave transparentes) foi **preservado** como
`build_solution_blueprint` (função pura) e **dobrado** em `save_solution_blueprint`: o
agente fornece requisitos/contexto/restrições, o builder deriva o blueprint estruturado
(com `triggered_by` rastreável) e a tool o persiste como histórico. Thin wrappers sobre
o `ArchitectureStore`."""

from __future__ import annotations

import re
from typing import Any

from ..db.store import ArchitectureStore
from ._common import as_str_list, match_hints, slug

# Heurísticas transparentes: palavra-chave → padrão arquitetural sugerido.
_PATTERN_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Event-Driven Architecture",
        ("event", "evento", "stream", "kafka", "queue", "fila", "pub/sub", "pubsub"),
    ),
    ("Microservices", ("microservi", "scal", "escal", "independent", "decoupl", "desacopl")),
    ("CQRS", ("cqrs", "read model", "write model", "command", "query")),
    ("API Gateway", ("api gateway", "gateway", "bff", "rate limit", "throttl")),
    ("Caching Layer", ("cache", "latency", "latência", "fast read", "performance")),
    ("Multi-Tenancy", ("tenant", "multi-tenant", "multitenant", "saas")),
    ("Layered (N-Tier)", ("crud", "monolith", "monólito", "simple", "simples")),
]

# Palavra-chave → preocupação não-funcional (NFR).
_NFR_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Security",
        ("secur", "segur", "auth", "oauth", "encrypt", "criptograf", "compliance", "gdpr", "lgpd", "pci"),
    ),
    ("Scalability", ("scal", "escal", "throughput", "load", "carga", "concurrent", "concorren")),
    (
        "Availability",
        ("availab", "disponib", "uptime", "ha", "high availability", "sla", "failover", "resilien"),
    ),
    ("Performance", ("performance", "latency", "latência", "fast", "rápid", "real-time", "tempo real")),
    ("Observability", ("observab", "monitor", "logging", "trace", "metric", "métric")),
    ("Data Consistency", ("consisten", "transaction", "transaç", "acid", "integrity", "integridade")),
]


def build_solution_blueprint(
    requirements: str = "",
    solution_name: str = "Solution",
    context: str = "",
    constraints: list[Any] | None = None,
) -> dict[str, Any]:
    """Deriva um blueprint de solução estruturado dos requisitos.

    Determinístico: padrões/NFRs saem de heurísticas de palavra-chave transparentes
    (``triggered_by``); componentes de negócio são extraídos das frases dos requisitos.
    Nada é fixo/inventado — é um scaffold estruturado rastreável."""
    solution_name = (solution_name or "Solution").strip() or "Solution"
    requirements = (requirements or "").strip()
    context = (context or "").strip()
    constraint_list = as_str_list(constraints)
    combined = f"{requirements}\n{context}\n{' '.join(constraint_list)}".strip()

    # Fragmenta os requisitos em itens acionáveis (por linha, ';' ou '.').
    raw_items = re.split(r"[\n;.]+", requirements)
    req_items = [item.strip() for item in raw_items if item.strip()]

    patterns = match_hints(combined, _PATTERN_HINTS)
    if not patterns:
        patterns = [
            {
                "name": "Layered (N-Tier)",
                "triggered_by": [],
                "note": "default — nenhum sinal específico detectado nos requisitos",
            }
        ]
    nfrs = match_hints(combined, _NFR_HINTS)

    business_components = [
        {"name": f"{slug(item)[:40] or 'capability'}_service", "requirement": item} for item in req_items
    ]
    layers = [
        {
            "name": "Presentation",
            "responsibility": "Interface com atores externos (UI/API pública)",
            "components": [f"{slug(solution_name)}_frontend"] if req_items else [],
        },
        {
            "name": "Application / API",
            "responsibility": "Orquestração de casos de uso e exposição de endpoints",
            "components": [f"{slug(solution_name)}_api"],
        },
        {
            "name": "Business Logic",
            "responsibility": "Regras de domínio derivadas dos requisitos",
            "components": [c["name"] for c in business_components] or ["core_domain"],
        },
        {
            "name": "Data",
            "responsibility": "Persistência e recuperação de estado",
            "components": ["primary_datastore"]
            + (["cache"] if any("Caching" in p["name"] for p in patterns) else []),
        },
    ]

    return {
        "title": f"Solution Blueprint — {solution_name}",
        "solution_name": solution_name,
        "input_requirements": req_items,
        "context": context,
        "constraints": constraint_list,
        "layers": layers,
        "components": business_components,
        "chosen_patterns": patterns,
        "non_functional_concerns": nfrs,
        "version": "1.0",
    }


async def save_solution_blueprint(
    store: ArchitectureStore,
    requirements: str,
    solution_name: str = "Solution",
    context: str = "",
    constraints: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Deriva o blueprint dos requisitos e o persiste (histórico)."""
    built = build_solution_blueprint(
        requirements=requirements,
        solution_name=solution_name,
        context=context,
        constraints=constraints,
    )
    blueprint = await store.save_solution_blueprint(
        solution_name=built["solution_name"],
        content=built,
        context=context or None,
        requirements=requirements or None,
        status=status,
    )
    return {"saved": True, "solution_blueprint": blueprint}


async def list_solution_blueprints(
    store: ArchitectureStore, solution_name: str | None = None, status: str | None = None
) -> dict[str, Any]:
    blueprints = await store.list_solution_blueprints(solution_name=solution_name, status=status)
    return {
        "total": len(blueprints),
        "filters": {"solution_name": solution_name, "status": status},
        "solution_blueprints": blueprints,
    }


async def get_solution_blueprint(store: ArchitectureStore, blueprint_id: int) -> dict[str, Any]:
    blueprint = await store.get_solution_blueprint(blueprint_id)
    if blueprint is None:
        return {"error": "not_found", "id": blueprint_id}
    return blueprint


async def update_solution_blueprint(
    store: ArchitectureStore,
    blueprint_id: int,
    context: str | None = None,
    content: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    blueprint = await store.update_solution_blueprint(
        blueprint_id, context=context, content=content, status=status
    )
    if blueprint is None:
        return {"error": "not_found", "id": blueprint_id}
    return {"updated": True, "solution_blueprint": blueprint}


async def delete_solution_blueprint(store: ArchitectureStore, blueprint_id: int) -> dict[str, Any]:
    deleted = await store.delete_solution_blueprint(blueprint_id)
    return {"deleted": deleted > 0, "id": blueprint_id, "deleted_count": deleted}
