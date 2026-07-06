"""Discovery API HTTP (ADR-011) — casca FastAPI sobre o CatalogStore.

Serve o Capability Registry como source of truth consultável. Substitui o
service-discovery simples do mcp-registry.py (que vira a faceta de *provider health*).

    python -m platform_catalog.app            # :8000
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query

from .registry import CatalogStore

app = FastAPI(title="Platform Capability Registry", version="0.1.0",
              description="Discovery API do catálogo de capabilities (ADR-009/010/011).")

_store: CatalogStore | None = None


def store() -> CatalogStore:
    global _store
    if _store is None:
        _store = CatalogStore().load()
    return _store


@app.get("/")
def root():
    return {"service": "platform-capability-registry", "version": "0.1.0",
            "spec": ["ADR-009", "ADR-010", "ADR-011"],
            "endpoints": ["/health", "/v1/operations", "/v1/operations/{uid}",
                          "/v1/operations/{uid}/tools", "/v1/operations/{uid}/resolve",
                          "/v1/providers", "/v1/providers/{id}", "/v1/stats"]}


@app.get("/health")
def health():
    return {"status": "healthy", "operations": len(store().operations)}


@app.get("/v1/operations")
def list_operations(
    domain: str | None = None, resource: str | None = None, effect: str | None = None,
    owner: str | None = None, risk: str | None = None,
    q: str | None = Query(None, description="busca livre"),
):
    s = store()
    if q is not None:
        ops = s.search(q)
    elif domain is not None:
        ops = s.list_by_domain(domain)
    elif resource is not None:
        ops = s.find_by_resource(resource)
    elif effect is not None:
        ops = s.find_by_effect(effect)
    elif owner is not None:
        ops = s.find_by_owner(owner)
    elif risk is not None:
        ops = s.find_by_risk(risk)
    else:
        ops = list(s.operations.values())
    return {"count": len(ops), "operations": [_brief(o) for o in ops]}


@app.get("/v1/operations/{uid}")
def get_operation(uid: str):
    op = store().get(uid)
    if op is None:
        raise HTTPException(status_code=404, detail=f"operation {uid!r} não existe")
    return op


@app.get("/v1/operations/{uid}/tools")
def operation_tools(uid: str):
    if store().get(uid) is None:
        raise HTTPException(status_code=404, detail=f"operation {uid!r} não existe")
    tools = store().list_tools_for(uid)
    return {"operation_id": uid, "count": len(tools),
            "tools": [t["spec"] for t in tools]}


@app.get("/v1/operations/{uid}/resolve")
def resolve(uid: str):
    if store().get(uid) is None:
        raise HTTPException(status_code=404, detail=f"operation {uid!r} não existe")
    chosen = store().resolve_tool(uid)
    if chosen is None:
        raise HTTPException(status_code=404, detail=f"operation {uid!r} não tem Tool binding")
    return chosen["spec"]


@app.get("/v1/providers")
def list_providers():
    p = store().providers
    return {"count": len(p), "providers": [e["spec"] | {"id": pid} for pid, e in p.items()]}


@app.get("/v1/providers/{pid}")
def get_provider(pid: str):
    p = store().providers.get(pid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"provider {pid!r} não existe")
    return p


@app.get("/v1/stats")
def stats():
    return store().stats()


@app.get("/v1/production-impact")
def production_impact():
    """Quem pode impactar produção? (checklist §7) — Operations de blast env/tenant/global
    + os providers que as implementam (rastreabilidade §6)."""
    s = store()
    ops = s.find_production_impacting()
    return {"count": len(ops),
            "operations": [_brief(o) | {"providers": s.providers_for(o["metadata"]["uid"])}
                           for o in ops]}


def _brief(op: dict) -> dict:
    m, s = op["metadata"], op["spec"]
    return {"uid": m["uid"], "domain": m["domain"], "capability": s["capability"],
            "resource": s["resource"]["type"], "operation": s["operation"],
            "authz": s["authz"], "risk": s["risk"]["default_level"],
            "approval": s["risk"]["approval_required"], "lifecycle": m["lifecycle"]}


def main() -> None:
    import uvicorn
    store()  # carrega no boot
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")),
                log_level="info")


if __name__ == "__main__":
    main()
