"""Gate de validação adversarial do seed do catálogo (checklist de 7 pontos).

Invariantes que o catálogo DEVE satisfazer para ser fonte de enforcement (não
"catálogo bonito"). Roda como gate de CI:

    python -m platform_catalog.validate      # exit 0 se limpo, 1 se violações

`validate_catalog(store)` retorna a lista de violações (vazia = OK).
"""

from __future__ import annotations

import re
import sys

from .registry import CatalogStore

# efeitos que NUNCA podem ser baixo risco (write perigoso).
DANGEROUS_EFFECTS = {"deploy", "delete", "rollback"}
ID_RE = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*$")   # <domínio|ns>.<tool>; ns externo pode ter hífen


def validate_catalog(store: CatalogStore) -> list[str]:
    v: list[str] = []

    for o in store.operations.values():
        uid = o["metadata"]["uid"]
        s = o["spec"]
        risk = s["risk"]
        authz, level = s["authz"], risk["default_level"]
        effects = set(risk["effects"])

        # §1 — nenhum write perigoso classificado como baixo
        if authz == "write" and level == "low":
            v.append(f"§1 write com default_level=low: {uid}")
        if (effects & DANGEROUS_EFFECTS) and level in ("low", "medium"):
            v.append(f"§1 efeito perigoso {sorted(effects & DANGEROUS_EFFECTS)} com level={level}: {uid}")

        # §2 — todo high/critical exige N2
        if level in ("high", "critical") and risk["approval_required"] != "N2":
            v.append(f"§2 level={level} sem approval N2: {uid}")

        # §3 — toda read é idempotente
        if authz == "read" and not s["contract"]["execution"]["idempotent"]:
            v.append(f"§3 read não-idempotente: {uid}")

        # §5 — Operation IDs estáveis e legíveis
        if not ID_RE.match(uid):
            v.append(f"§5 id fora do padrão <domínio>.<tool>: {uid}")

        # §6 — rastreabilidade: toda Operation tem ≥1 Tool binding
        if not store.list_tools_for(uid):
            v.append(f"§6 Operation sem Tool binding: {uid}")

    # §4 — multi-binding não pode ter provider duplicado (colapso indevido)
    for uid in {t["spec"]["operation_id"] for t in store.tools}:
        provs = [t["spec"]["provider_id"] for t in store.list_tools_for(uid)]
        if len(provs) != len(set(provs)):
            v.append(f"§4 Operation com provider duplicado (merge indevido?): {uid}")

    # §6 — todo Tool binding é rastreável até uma Operation + tem provider/tool
    for t in store.tools:
        sp = t["spec"]
        if sp["operation_id"] not in store.operations:
            v.append(f"§6 Tool binding órfão (operation inexistente): {t['metadata']['uid']}")
        if not sp.get("provider_id") or not sp.get("tool"):
            v.append(f"§6 Tool binding sem provider/tool: {t['metadata']['uid']}")

    # §7 — o catálogo consegue responder "quem pode impactar produção?"
    prod = store.find_production_impacting()
    if not prod:
        v.append("§7 nenhuma Operation de impacto em produção — query vazia (suspeito)")
    for o in prod:
        if o["spec"]["authz"] != "write":
            v.append(f"§7 impacto-produção mas authz!=write: {o['metadata']['uid']}")

    # §8 — assets (Fase 5, ADR-014): relações resolvem; Runbook referencia Operation.
    for uid, a in store.assets.items():
        kind = a["kind"]
        # Runbook: toda task com operation_id (resolvida) tem de existir como Operation.
        if kind == "Runbook":
            for t in a["spec"].get("tasks", []):
                op = t.get("operation_id")
                if op is not None and op not in store.operations:
                    v.append(f"§8 Runbook {uid} task {t.get('task_id')} → operation inexistente: {op}")
        # Relações estruturais (Persona/Prompt/Policy) devem resolver a op/asset.
        # ADR: relações são parse best-effort → não bloqueiam.
        if kind != "ADR":
            for r in a.get("relations", []):
                tgt = r.get("target")
                if tgt and not store.ref_exists(tgt):
                    v.append(f"§8 asset {uid} relação {r.get('verb')} → alvo inexistente: {tgt}")

    return v


def main() -> int:
    store = CatalogStore().load()
    violations = validate_catalog(store)
    if violations:
        print(f"CATALOG INVÁLIDO — {len(violations)} violação(ões):")
        for x in violations:
            print(f"  - {x}")
        return 1
    print(f"CATALOG OK — {len(store.operations)} operations + {len(store.assets)} assets, "
          f"0 violações (§1-§8). Produção-impactante: {len(store.find_production_impacting())} ops.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
