"""Tools de modelo C4 — persistem o modelo C4 (upsert por sistema).

O antigo `generate_c4_diagram` (construção 100% determinística de um modelo C4 —
System Context + Container — a partir de atores/containers/relações) foi **preservado**
como `build_c4_model` (função pura) e **dobrado** em `set_c4_diagram`: o agente fornece
os inputs, o builder deriva o modelo estruturado (nada inventado) e a tool o persiste
(upsert por `system_name` — um modelo C4 canônico por sistema). Thin wrappers sobre o
`ArchitectureStore`."""

from __future__ import annotations

from typing import Any

from ..db.store import ArchitectureStore
from ._common import slug


def build_c4_model(
    system_name: str = "System",
    actors: list[Any] | None = None,
    containers: list[Any] | None = None,
    relationships: list[Any] | None = None,
) -> dict[str, Any]:
    """Constrói um modelo C4 (System Context + Container) a partir dos inputs.

    Determinístico: nenhum ator/container/relação é inventado — apenas os fornecidos
    aparecem. ``actors``/``containers`` aceitam ``str`` (nome) ou ``dict``;
    ``relationships`` aceita ``{source,target,...}`` ou a forma curta ``"A -> B"``.
    """
    system_name = (system_name or "System").strip() or "System"
    system_id = slug(system_name)

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
        actor_nodes.append({"id": slug(name), "name": name, "type": atype, "description": desc})

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
        container_nodes.append({"id": slug(name), "name": name, "technology": tech, "description": desc})

    # --- Índice nome→id para resolver relações ------------------------------- #
    name_to_id: dict[str, str] = {system_name: system_id}
    for node in actor_nodes:
        name_to_id[node["name"]] = node["id"]
    for node in container_nodes:
        name_to_id[node["name"]] = node["id"]

    def _resolve(label: str) -> dict[str, Any]:
        label = (label or "").strip()
        return {"ref": label, "id": name_to_id.get(label, slug(label))}

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
    }


async def set_c4_diagram(
    store: ArchitectureStore,
    system_name: str,
    actors: list[Any] | None = None,
    containers: list[Any] | None = None,
    relationships: list[Any] | None = None,
    model: Any = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Deriva (ou aceita pronto) o modelo C4 e persiste por sistema (upsert)."""
    built = model if model is not None else build_c4_model(system_name, actors, containers, relationships)
    title = built.get("title") if isinstance(built, dict) else None
    diagram = await store.set_c4_diagram(system_name=system_name, model=built, title=title, status=status)
    return {"saved": True, "c4_diagram": diagram}


async def list_c4_diagrams(store: ArchitectureStore, status: str | None = None) -> dict[str, Any]:
    diagrams = await store.list_c4_diagrams(status=status)
    return {"total": len(diagrams), "filters": {"status": status}, "c4_diagrams": diagrams}


async def get_c4_diagram(store: ArchitectureStore, system_name: str) -> dict[str, Any]:
    diagram = await store.get_c4_diagram(system_name)
    if diagram is None:
        return {"error": "not_found", "system_name": system_name}
    return diagram


async def delete_c4_diagram(store: ArchitectureStore, system_name: str) -> dict[str, Any]:
    deleted = await store.delete_c4_diagram(system_name)
    return {"deleted": deleted > 0, "system_name": system_name, "deleted_count": deleted}
