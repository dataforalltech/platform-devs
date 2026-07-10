"""Architecture MCP tools.

Todas as ferramentas derivam a saída DOS INPUTS recebidos — nada de listas fixas
ou constantes canônicas. Onde a análise "real" exigiria raciocínio generativo/LLM
(por exemplo, decidir qual padrão arquitetural é ideal para um requisito em prosa),
a implementação constrói um *scaffold estruturado determinístico* a partir dos
inputs (heurísticas transparentes por palavra-chave) em vez de inventar análise.
Essa limitação está documentada no campo ``_meta.limitation`` de cada saída e no
``skipped`` do relatório final do agente.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "generate_c4_diagram",
    "generate_solution_blueprint",
    "generate_architecture",
    "status",
    "SERVER_NAME",
]

SERVER_NAME = "architecture-mcp"


# ──────────────────────────────────────────────────────────────────────────── #
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────── #
def _slug(text: str) -> str:
    """Gera um id estável (slug) a partir de um rótulo livre."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "unnamed"


def _as_str_list(value: Any) -> list[str]:
    """Normaliza um input que pode vir como str única, lista ou None em list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _server_version() -> str:
    """Lê a versão declarada no pyproject.toml do servidor (não hardcoded)."""
    # architecture_tools.py → src/tools/ ; pyproject fica 3 níveis acima.
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    # Procura a primeira linha `version = "x.y.z"` na seção [project].
    match = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', text)
    return match.group(1) if match else "unknown"


# ──────────────────────────────────────────────────────────────────────────── #
# 1) C4 diagram — determinístico, 100% derivado dos inputs
# ──────────────────────────────────────────────────────────────────────────── #
def generate_c4_diagram(
    system_name: str = "System",
    actors: list[Any] | None = None,
    containers: list[Any] | None = None,
    relationships: list[Any] | None = None,
) -> dict[str, Any]:
    """Constrói um modelo C4 (System Context + Container) a partir dos inputs.

    Parâmetros
    ----------
    system_name:
        Nome do software system em foco.
    actors:
        Pessoas/sistemas externos. Cada item pode ser uma ``str`` (nome) ou um
        ``dict`` com chaves ``name`` (obrigatória), ``type`` (``"person"`` |
        ``"external_system"``, default ``"person"``) e ``description``.
    containers:
        Aplicações/serviços/data stores internos ao sistema. Cada item pode ser
        uma ``str`` (nome) ou ``dict`` com ``name``, ``technology`` e
        ``description``.
    relationships:
        Arestas do diagrama. Cada item é ``dict`` com ``source`` e ``target``
        (nomes de atores/containers/sistema) e opcionalmente ``description`` e
        ``technology``. Aceita também a forma curta ``"A -> B"`` (str).

    Retorna um modelo C4 com os níveis 1 (System Context) e 2 (Container).
    A saída é totalmente determinística: nenhum ator/container/relação é
    inventado — apenas os fornecidos aparecem.
    """
    system_name = (system_name or "System").strip() or "System"
    system_id = _slug(system_name)

    # --- Atores (nível 1) ---------------------------------------------------- #
    actor_nodes: list[dict[str, Any]] = []
    actor_names: set[str] = set()
    for raw in actors or []:
        if isinstance(raw, dict):
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            atype = str(raw.get("type", "person")).strip() or "person"
            desc = str(raw.get("description", "")).strip()
        else:
            name = str(raw).strip()
            if not name:
                continue
            atype = "person"
            desc = ""
        if name in actor_names:
            continue
        actor_names.add(name)
        actor_nodes.append(
            {
                "id": _slug(name),
                "name": name,
                "type": atype,
                "description": desc,
            }
        )

    # --- Containers (nível 2) ------------------------------------------------ #
    container_nodes: list[dict[str, Any]] = []
    container_names: set[str] = set()
    for raw in containers or []:
        if isinstance(raw, dict):
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            tech = str(raw.get("technology", "")).strip()
            desc = str(raw.get("description", "")).strip()
        else:
            name = str(raw).strip()
            if not name:
                continue
            tech = ""
            desc = ""
        if name in container_names:
            continue
        container_names.add(name)
        container_nodes.append(
            {
                "id": _slug(name),
                "name": name,
                "technology": tech,
                "description": desc,
            }
        )

    # --- Índice nome→id para resolver relações ------------------------------- #
    name_to_id: dict[str, str] = {system_name: system_id}
    for node in actor_nodes:
        name_to_id[node["name"]] = node["id"]
    for node in container_nodes:
        name_to_id[node["name"]] = node["id"]

    def _resolve(label: str) -> dict[str, Any]:
        label = (label or "").strip()
        return {"ref": label, "id": name_to_id.get(label, _slug(label))}

    # --- Relações ------------------------------------------------------------ #
    rel_edges: list[dict[str, Any]] = []
    for raw in relationships or []:
        if isinstance(raw, dict):
            source = str(raw.get("source", "")).strip()
            target = str(raw.get("target", "")).strip()
            desc = str(raw.get("description", "")).strip()
            tech = str(raw.get("technology", "")).strip()
        elif isinstance(raw, str) and "->" in raw:
            source, _, target = raw.partition("->")
            source, target = source.strip(), target.strip()
            desc = ""
            tech = ""
        else:
            continue
        if not source or not target:
            continue
        src = _resolve(source)
        tgt = _resolve(target)
        rel_edges.append(
            {
                "source": src["ref"],
                "source_id": src["id"],
                "target": tgt["ref"],
                "target_id": tgt["id"],
                "description": desc,
                "technology": tech,
            }
        )

    return {
        "title": f"C4 Model — {system_name}",
        "system": {"id": system_id, "name": system_name},
        "levels": {
            "system_context": {
                "level": 1,
                "name": "System Context",
                "software_system": {"id": system_id, "name": system_name},
                "actors": actor_nodes,
                "relationships": rel_edges,
            },
            "container": {
                "level": 2,
                "name": "Container",
                "software_system": {"id": system_id, "name": system_name},
                "containers": container_nodes,
                "relationships": rel_edges,
            },
        },
        "summary": {
            "actor_count": len(actor_nodes),
            "container_count": len(container_nodes),
            "relationship_count": len(rel_edges),
        },
        "status": "generated",
        "_meta": {
            "deterministic": True,
            "generated_at": _now_iso(),
        },
    }


# ──────────────────────────────────────────────────────────────────────────── #
# 2) Solution blueprint — scaffold estruturado a partir de requisitos
# ──────────────────────────────────────────────────────────────────────────── #
# Heurísticas transparentes de palavra-chave → padrão arquitetural sugerido.
_PATTERN_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Event-Driven Architecture",
        ("event", "evento", "stream", "kafka", "queue", "fila", "pub/sub", "pubsub"),
    ),
    (
        "Microservices",
        ("microservi", "scal", "escal", "independent", "decoupl", "desacopl"),
    ),
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
        (
            "secur",
            "segur",
            "auth",
            "oauth",
            "encrypt",
            "criptograf",
            "compliance",
            "gdpr",
            "lgpd",
            "pci",
        ),
    ),
    (
        "Scalability",
        ("scal", "escal", "throughput", "load", "carga", "concurrent", "concorren"),
    ),
    (
        "Availability",
        (
            "availab",
            "disponib",
            "uptime",
            "ha",
            "high availability",
            "sla",
            "failover",
            "resilien",
        ),
    ),
    (
        "Performance",
        (
            "performance",
            "latency",
            "latência",
            "fast",
            "rápid",
            "real-time",
            "tempo real",
        ),
    ),
    ("Observability", ("observab", "monitor", "logging", "trace", "metric", "métric")),
    (
        "Data Consistency",
        ("consisten", "transaction", "transaç", "acid", "integrity", "integridade"),
    ),
]


def _match_hints(text: str, hints: list[tuple[str, tuple[str, ...]]]) -> list[dict[str, Any]]:
    lowered = text.lower()
    matched: list[dict[str, Any]] = []
    for label, keywords in hints:
        triggers = [kw for kw in keywords if kw in lowered]
        if triggers:
            matched.append({"name": label, "triggered_by": triggers})
    return matched


def generate_solution_blueprint(
    requirements: str = "",
    solution_name: str = "Solution",
    context: str = "",
    constraints: list[Any] | None = None,
) -> dict[str, Any]:
    """Deriva um blueprint de solução estruturado a partir dos requisitos.

    Parâmetros
    ----------
    requirements:
        Texto livre descrevendo os requisitos funcionais/de negócio.
    solution_name:
        Nome da solução (aparece no título).
    context:
        Contexto adicional (ex.: domínio, restrições organizacionais).
    constraints:
        Lista de restrições técnicas/organizacionais (str ou list[str]).

    A escolha de padrões e NFRs usa heurísticas de palavra-chave transparentes
    (``triggered_by`` mostra o que disparou cada sugestão). Componentes por
    camada são extraídos das frases dos requisitos — nada é fixo. Ver
    ``_meta.limitation``.
    """
    solution_name = (solution_name or "Solution").strip() or "Solution"
    requirements = (requirements or "").strip()
    context = (context or "").strip()
    constraint_list = _as_str_list(constraints)
    combined = f"{requirements}\n{context}\n{' '.join(constraint_list)}".strip()

    # Fragmenta os requisitos em itens acionáveis (por linha, ';' ou '.').
    raw_items = re.split(r"[\n;.]+", requirements)
    req_items = [item.strip() for item in raw_items if item.strip()]

    # Padrões e NFRs sugeridos (derivados do texto, com rastreabilidade).
    patterns = _match_hints(combined, _PATTERN_HINTS)
    if not patterns:
        patterns = [
            {
                "name": "Layered (N-Tier)",
                "triggered_by": [],
                "note": "default — nenhum sinal específico detectado nos requisitos",
            }
        ]
    nfrs = _match_hints(combined, _NFR_HINTS)

    # Componentes por camada, derivados dos requisitos.
    # Cada requisito vira um componente na camada de negócio; camadas de borda
    # e dados listam os requisitos como capacidades que devem suportar.
    business_components = [
        {"name": f"{_slug(item)[:40] or 'capability'}_service", "requirement": item} for item in req_items
    ]
    layers = [
        {
            "name": "Presentation",
            "responsibility": "Interface com atores externos (UI/API pública)",
            "components": [f"{_slug(solution_name)}_frontend"] if req_items else [],
        },
        {
            "name": "Application / API",
            "responsibility": "Orquestração de casos de uso e exposição de endpoints",
            "components": [f"{_slug(solution_name)}_api"],
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
        "status": "draft",
        "version": "1.0",
        "_meta": {
            "deterministic": True,
            "generated_at": _now_iso(),
            "limitation": (
                "A seleção de padrões/NFRs usa heurísticas de palavra-chave "
                "transparentes (campo 'triggered_by'), não raciocínio arquitetural "
                "generativo. Trate como scaffold estruturado, não como análise final."
            ),
        },
    }


# ──────────────────────────────────────────────────────────────────────────── #
# 3) Architecture proposal — scaffold a partir de domínio + restrições
# ──────────────────────────────────────────────────────────────────────────── #
_STYLE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Event-Driven Microservices",
        ("event", "evento", "stream", "kafka", "assíncron", "async"),
    ),
    (
        "Microservices",
        (
            "microservi",
            "scal",
            "escal",
            "independent",
            "decoupl",
            "desacopl",
            "distributed",
            "distribuíd",
        ),
    ),
    (
        "Serverless",
        ("serverless", "lambda", "function", "faas", "pay-per-use", "sob demanda"),
    ),
    (
        "Modular Monolith",
        (
            "monolith",
            "monólito",
            "single deploy",
            "startup",
            "mvp",
            "simple",
            "simples",
        ),
    ),
    ("Layered (N-Tier)", ("crud", "traditional", "tradicional")),
]


def generate_architecture(
    domain: str = "",
    constraints: list[Any] | None = None,
    quality_attributes: list[Any] | None = None,
    architecture_name: str = "",
) -> dict[str, Any]:
    """Deriva uma proposta de arquitetura a partir de domínio e restrições.

    Parâmetros
    ----------
    domain:
        Domínio/negócio-alvo (ex.: "e-commerce", "IoT telemetry").
    constraints:
        Restrições técnicas/organizacionais (str ou list[str]) — ex.: "budget
        baixo", "on-premises", "compliance PCI".
    quality_attributes:
        Atributos de qualidade priorizados (str ou list[str]) — ex.:
        "scalability", "low latency".
    architecture_name:
        Nome opcional; default derivado do domínio.

    O estilo arquitetural é escolhido por heurísticas de palavra-chave
    transparentes sobre domínio + restrições + atributos de qualidade
    (``rationale.triggered_by``). Ver ``_meta.limitation``.
    """
    domain = (domain or "").strip()
    constraint_list = _as_str_list(constraints)
    qa_list = _as_str_list(quality_attributes)
    name = (architecture_name or "").strip() or (
        f"{domain} architecture".strip() if domain else "Architecture"
    )
    combined = f"{domain}\n{' '.join(constraint_list)}\n{' '.join(qa_list)}".strip()

    style_matches = _match_hints(combined, _STYLE_HINTS)
    if style_matches:
        chosen = style_matches[0]
        alternatives = [m["name"] for m in style_matches[1:]]
        rationale = {
            "style": chosen["name"],
            "triggered_by": chosen["triggered_by"],
        }
    else:
        rationale = {
            "style": "Modular Monolith",
            "triggered_by": [],
            "note": "default — nenhum sinal específico detectado; opção de menor custo inicial",
        }
        alternatives = ["Microservices"]

    # Building blocks derivados: cada atributo de qualidade aponta uma tática.
    _qa_tactics = {
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
    tactics = []
    for qa in qa_list:
        tactic = _qa_tactics.get(qa.strip().lower())
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
        "status": "proposed",
        "_meta": {
            "deterministic": True,
            "generated_at": _now_iso(),
            "limitation": (
                "A escolha de estilo e táticas usa heurísticas de palavra-chave "
                "transparentes, não raciocínio arquitetural generativo. Trate como "
                "scaffold estruturado derivado dos inputs, não como decisão final."
            ),
        },
    }


# ──────────────────────────────────────────────────────────────────────────── #
# 4) status — status real do servidor
# ──────────────────────────────────────────────────────────────────────────── #
def status() -> dict[str, Any]:
    """Retorna o status real do servidor (nome, versão do pyproject, nº de tools, timestamp)."""
    tool_names = [
        "generate_c4_diagram",
        "generate_solution_blueprint",
        "generate_architecture",
        "status",
    ]
    return {
        "name": SERVER_NAME,
        "status": "ok",
        "version": _server_version(),
        "tool_count": len(tool_names),
        "tools": tool_names,
        "timestamp": _now_iso(),
    }
