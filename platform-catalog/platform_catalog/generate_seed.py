"""Gera o seed do Capical Registry a partir de seed/tool_inventory.json.

Cada tool -> um Tool binding; tools que derivam ao mesmo operation_id (mesmo domínio +
mesmo nome) MERGEIAM numa única Operation com N bindings (portabilidade — ADR-009 D9.3).
Emite YAML no envelope ADR-010 em catalog/{operations,tools,providers}/.

    python -m platform_catalog.generate_seed
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .derive import derive_operation, provider_id
from .models import (
    API_VERSION, Entity, Kind, Metadata, ProviderSpec, Relation, RelationVerb, ToolSpec,
)

ROOT = Path(__file__).resolve().parents[1]           # platform-catalog/
INVENTORY = ROOT / "seed" / "tool_inventory.json"
CATALOG = ROOT / "catalog"


def _safe(name: str) -> str:
    return name.replace("/", "_").replace(".", "__").replace(":", "-")


def _dump(entity: Entity, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = entity.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def build() -> dict:
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))["tools"]
    operations: dict[str, Entity] = {}
    tools: list[Entity] = []
    providers: dict[str, Entity] = {}
    bindings_per_op: dict[str, int] = {}

    for row in inv:
        server, tool, cap = row["server"], row["tool"], row["capability"]
        pid = provider_id(server)
        op_id, spec, meta = derive_operation(server, tool, cap)

        # Operation (merge por op_id — 1ª ocorrência define o contrato)
        if op_id not in operations:
            operations[op_id] = Entity(
                kind=Kind.OPERATION, metadata=meta, spec=spec.model_dump(mode="json"),
                relations=[Relation(verb=RelationVerb.ACTS_ON,
                                    target=f"resource:{spec.resource.type}")],
            )
        bindings_per_op[op_id] = bindings_per_op.get(op_id, 0) + 1

        # Tool binding (sempre um por tool físico)
        tool_uid = f"{pid}:{tool}"
        tools.append(Entity(
            kind=Kind.TOOL,
            metadata=Metadata(name=f"{pid}/{tool}", uid=tool_uid, domain=meta.domain,
                              title=f"{tool} @ {pid}", tags=[pid, meta.domain]),
            spec=ToolSpec(operation_id=op_id, provider_id=pid, tool=tool).model_dump(mode="json"),
            relations=[Relation(verb=RelationVerb.IMPLEMENTS, target=op_id),
                       Relation(verb=RelationVerb.PROVIDED_BY, target=pid)],
        ))

        # Provider (único por server)
        if pid not in providers:
            providers[pid] = Entity(
                kind=Kind.PROVIDER,
                metadata=Metadata(name=pid, uid=pid, domain=meta.domain, title=pid,
                                  tags=[meta.domain]),
                spec=ProviderSpec(server=server).model_dump(mode="json"),
            )

    return {"operations": operations, "tools": tools, "providers": providers,
            "bindings_per_op": bindings_per_op}


def main() -> None:
    b = build()
    # limpa e regrava
    for sub in ("operations", "tools", "providers"):
        d = CATALOG / sub
        if d.exists():
            for f in d.glob("*.yaml"):
                f.unlink()
    for op_id, ent in b["operations"].items():
        _dump(ent, CATALOG / "operations" / f"{_safe(op_id)}.yaml")
    for ent in b["tools"]:
        _dump(ent, CATALOG / "tools" / f"{_safe(ent.metadata.uid)}.yaml")
    for pid, ent in b["providers"].items():
        _dump(ent, CATALOG / "providers" / f"{_safe(pid)}.yaml")

    portab = {k: v for k, v in b["bindings_per_op"].items() if v > 1}
    index = {
        "apiVersion": API_VERSION,
        "counts": {"operations": len(b["operations"]), "tools": len(b["tools"]),
                   "providers": len(b["providers"])},
        "portability": {"operations_with_multiple_tools": len(portab), "examples": portab},
    }
    (CATALOG / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
    print(f"operations={len(b['operations'])} tools={len(b['tools'])} providers={len(b['providers'])}")
    print(f"portability (Operations com >1 Tool): {len(portab)} -> {portab}")


if __name__ == "__main__":
    main()
