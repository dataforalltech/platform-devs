"""Fase 1.1 — federação de tools EXTERNAS do gateway para o catálogo.

O gateway `platform-mcp` federa tools de servidores de OUTROS repos (platform-admin,
platform-auth, platform-governance, …) que o platform-devs NÃO possui. Esta máquina
ingere um `tools/list` do gateway (`seed/gateway_tools.json`) e materializa Operations
EXTERNAS no catálogo (marcadas `external: true`, `owner` = repo de origem), com Tool
bindings resolvíveis por `<namespace>.<tool>`. Assim runbooks que usam essas tools
(ex.: platform_health) passam a RESOLVER, sem o platform-devs 'possuir' o que é externo.

    # 1) dump do gateway vivo (script no scratchpad) -> seed/gateway_tools.json
    # 2) python -m platform_catalog.federate           -> materializa as ops externas
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .models import (
    API_VERSION, BlastRadius, Capability, Contract, Entity, Execution, Kind, Metadata,
    OperationSpec, ProviderSpec, Relation, RelationVerb, Resource, Risk, RiskLevel, ToolSpec,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "seed" / "gateway_tools.json"
CATALOG = ROOT / "catalog"

# namespace do gateway -> (domínio, repo dono)
NS_INFO = {
    "admin": ("platform", "platform-admin"), "auth": ("identity", "platform-auth"),
    "governance": ("governance", "platform-governance"), "api-gateway": ("infra", "platform-api-gateway"),
    "cache": ("infra", "external"), "connectors": ("integration", "external"),
    "scheduler": ("platform", "external"), "session": ("platform", "platform-devs"),
    "dev-twin": ("identity", "platform-devs"), "audit": ("governance", "platform-devs"),
}
_WRITE_VERBS = {"create", "update", "delete", "set", "register", "unregister", "revoke",
                "rotate", "reset", "assign", "manage", "refresh", "add", "remove", "grant",
                "enable", "disable", "sync", "invalidate", "clear", "import", "rebuild"}
_WRITE_EFFECTS = {"create": ["write"], "delete": ["delete"], "revoke": ["write"],
                  "manage": ["write"], "rotate": ["write"], "reset": ["write"],
                  "assign": ["write"], "grant": ["write"]}


def _safe(name: str) -> str:
    return name.replace("/", "_").replace(".", "__").replace(":", "-")


def _derive(namespace: str, tool: str) -> tuple[OperationSpec, str]:
    domain, _ = NS_INFO.get(namespace, ("external", "external"))
    verb = tool.split("_")[0].lower()
    write = verb in _WRITE_VERBS
    cap = Capability.WRITE if write else Capability.READ
    effects = _WRITE_EFFECTS.get(verb, ["write"]) if write else ["read"]
    # externo: 'delete/reset/rotate' em admin/auth atinge tenant; senão service; read=none.
    if not write:
        blast, level = BlastRadius.NONE, RiskLevel.LOW
    elif "delete" in effects or namespace in ("admin", "auth", "governance"):
        blast, level = BlastRadius.TENANT, RiskLevel.HIGH
    else:
        blast, level = BlastRadius.SERVICE, RiskLevel.MEDIUM
    approval = "N2" if level is RiskLevel.HIGH else "none"
    op_id = f"{namespace}.{tool}"
    spec = OperationSpec(
        domain=domain, capability=namespace, resource=Resource(type=namespace),
        operation=verb, authz=cap,
        risk=Risk(effects=effects, requires=[namespace], blast_radius=blast,
                  default_level=level, approval_required=approval),  # type: ignore[arg-type]
        contract=Contract(execution=Execution(idempotent=not write, side_effects=write)),
    )
    return spec, op_id


def build(inventory: list[dict]) -> dict:
    operations: dict[str, Entity] = {}
    tools: list[Entity] = []
    providers: dict[str, Entity] = {}
    for row in inventory:
        ns, tool = row["namespace"], row["tool"]
        domain, owner = NS_INFO.get(ns, ("external", "external"))
        spec, op_id = _derive(ns, tool)
        if op_id not in operations:
            meta = Metadata(name=f"{domain}/{tool}", uid=op_id, domain=domain, title=tool,
                            owner=owner, tags=[domain, "external", ns])
            operations[op_id] = Entity(kind=Kind.OPERATION, metadata=meta,
                                       spec={**spec.model_dump(mode="json"), "external": True},
                                       relations=[Relation(verb=RelationVerb.ACTS_ON,
                                                           target=f"resource:{ns}")])
        tools.append(Entity(
            kind=Kind.TOOL,
            metadata=Metadata(name=f"{ns}/{tool}", uid=f"{ns}:{tool}", domain=domain,
                              title=f"{tool} @ {ns} (external)", owner=owner, tags=[ns, "external"]),
            spec={**ToolSpec(operation_id=op_id, provider_id=ns, tool=tool).model_dump(mode="json"),
                  "external": True},
            relations=[Relation(verb=RelationVerb.IMPLEMENTS, target=op_id),
                       Relation(verb=RelationVerb.PROVIDED_BY, target=ns)]))
        if ns not in providers:
            providers[ns] = Entity(kind=Kind.PROVIDER,
                                   metadata=Metadata(name=ns, uid=ns, domain=domain, title=ns,
                                                     owner=owner, tags=[domain, "external"]),
                                   spec={**ProviderSpec(server=f"{ns} (federated)").model_dump(mode="json"),
                                         "external": True})
    return {"operations": operations, "tools": tools, "providers": providers}


def _dump(entity: Entity, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(entity.model_dump(mode="json"), sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")


def main() -> None:
    if not INVENTORY.exists():
        print(f"sem {INVENTORY} — rode o dump do gateway (scratchpad/dump_gateway_catalog.py)")
        return
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))["tools"]
    b = build(inv)
    ext = CATALOG / "external"      # separado do seed owned (generate_seed não mexe aqui)
    for op_id, ent in b["operations"].items():
        _dump(ent, ext / "operations" / f"{_safe(op_id)}.yaml")
    for ent in b["tools"]:
        _dump(ent, ext / "tools" / f"{_safe(ent.metadata.uid)}.yaml")
    for ns, ent in b["providers"].items():
        _dump(ent, ext / "providers" / f"{_safe(ns)}.yaml")
    print(f"federadas {len(b['operations'])} operations externas de "
          f"{len(b['providers'])} providers ({len(inv)} tools do gateway)")


if __name__ == "__main__":
    main()
