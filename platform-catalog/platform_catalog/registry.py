"""CatalogStore — carrega o catálogo YAML e implementa a Discovery API (ADR-011).

Leitura pura sobre o catálogo declarativo (source of truth do ADR-009). A API de
consulta (D11.2) e a política de seleção de Tool (D11.6) vivem aqui; o serviço HTTP
(app.py) é uma casca fina por cima.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CATALOG = _ROOT / "catalog"

# ordem lexicográfica de seleção quando N Tools implementam a mesma Operation (D11.6).
# Sem health ao vivo na Fase-1: usa preference (maior) -> provider_version (maior) -> provider_id.
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class CatalogStore:
    def __init__(self, catalog_dir: Path | None = None) -> None:
        self.dir = catalog_dir or _CATALOG
        self.operations: dict[str, dict] = {}
        self.tools: list[dict] = []
        self.providers: dict[str, dict] = {}
        self._tools_by_op: dict[str, list[dict]] = {}

    def load(self) -> "CatalogStore":
        self.operations = {e["metadata"]["uid"]: e for e in self._read("operations")}
        self.tools = self._read("tools")
        self.providers = {e["metadata"]["uid"]: e for e in self._read("providers")}
        self._tools_by_op = {}
        for t in self.tools:
            self._tools_by_op.setdefault(t["spec"]["operation_id"], []).append(t)
        return self

    def _read(self, sub: str) -> list[dict]:
        d = self.dir / sub
        if not d.exists():
            return []
        return [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.yaml"))]

    # --- Discovery API (ADR-011 D11.2) --------------------------------------
    def get(self, uid: str) -> dict | None:
        return self.operations.get(uid)

    def list_by_domain(self, domain: str) -> list[dict]:
        return [o for o in self.operations.values() if o["metadata"]["domain"] == domain]

    def find_by_resource(self, resource_type: str) -> list[dict]:
        return [o for o in self.operations.values()
                if o["spec"]["resource"]["type"] == resource_type]

    def find_by_effect(self, effect: str) -> list[dict]:
        return [o for o in self.operations.values()
                if effect in o["spec"]["risk"]["effects"]]

    def find_by_owner(self, owner: str) -> list[dict]:
        return [o for o in self.operations.values() if o["metadata"]["owner"] == owner]

    def find_by_risk(self, level: str) -> list[dict]:
        return [o for o in self.operations.values()
                if o["spec"]["risk"]["default_level"] == level]

    #: blast radii que atingem produção/ambiente compartilhado (checklist §7).
    PRODUCTION_BLAST = ("environment", "tenant", "global")

    def find_production_impacting(self) -> list[dict]:
        """"Quem pode impactar produção?" — Operations cujo blast_radius atinge
        ambiente/tenant/global (ADR-009 D9.5). Enforcement, não decoração."""
        return [o for o in self.operations.values()
                if o["spec"]["risk"]["blast_radius"] in self.PRODUCTION_BLAST]

    def providers_for(self, uid: str) -> list[str]:
        """Providers que implementam a Operation (rastreabilidade — checklist §6)."""
        return sorted({t["spec"]["provider_id"] for t in self._tools_by_op.get(uid, [])})

    def search(self, q: str) -> list[dict]:
        ql = q.lower()
        out = []
        for o in self.operations.values():
            m, s = o["metadata"], o["spec"]
            hay = " ".join([m["uid"], m["title"], m["domain"], s["capability"],
                            s["resource"]["type"], s["operation"], " ".join(m["tags"])]).lower()
            if ql in hay:
                out.append(o)
        return out

    def list_tools_for(self, operation_id: str) -> list[dict]:
        return list(self._tools_by_op.get(operation_id, []))

    def resolve_tool(self, operation_id: str) -> dict | None:
        """Escolhe o melhor Tool binding (D11.6). Fase-1: preference desc -> provider_version desc."""
        cands = self.list_tools_for(operation_id)
        if not cands:
            return None

        def key(t: dict):
            sel = t["spec"].get("selection", {}) or {}
            return (-int(sel.get("preference", 0)),
                    _semver_key(t["spec"].get("provider_version", "0")),
                    t["spec"]["provider_id"])

        return sorted(cands, key=key)[0]

    def stats(self) -> dict:
        by_domain: dict[str, int] = {}
        by_risk: dict[str, int] = {}
        writes = 0
        for o in self.operations.values():
            by_domain[o["metadata"]["domain"]] = by_domain.get(o["metadata"]["domain"], 0) + 1
            lvl = o["spec"]["risk"]["default_level"]
            by_risk[lvl] = by_risk.get(lvl, 0) + 1
            if o["spec"]["authz"] == "write":
                writes += 1
        multi = sum(1 for v in self._tools_by_op.values() if len(v) > 1)
        return {
            "operations": len(self.operations), "tools": len(self.tools),
            "providers": len(self.providers),
            "operations_by_domain": dict(sorted(by_domain.items())),
            "operations_by_risk": by_risk,
            "write_operations": writes,
            "operations_with_multiple_tools": multi,
        }


def _semver_key(v: str) -> tuple:
    parts = []
    for p in str(v).split("."):
        parts.append(-int(p) if p.isdigit() else 0)   # maior versão primeiro
    return tuple(parts)
