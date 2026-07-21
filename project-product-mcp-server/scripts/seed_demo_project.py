"""Seed idempotente de um projeto demo + repository_bindings github (ADR-017 G9).

Pronto para rodar APOS o project-product ser deployado (o G9 pede "seed >=1 projeto real
com bindings github"). Chama a API interna (S2S) de forma idempotente: cada create usa uma
``idempotency_key`` fixa, entao re-rodar devolve o mesmo recurso (replay no ledger), sem
duplicar. Os payloads sao construidos com os proprios models Pydantic (ProductCreate/
ProjectCreate/RepositoryBindingCreate + ExternalLink), garantindo dados contract-validos.

Uso:
    PROJECT_PRODUCT_INTERNAL_TOKEN=<token> \\
    PROJECT_PRODUCT_BASE_URL=http://localhost:8000 \\
    PROJECT_PRODUCT_TENANT_ID=dataforall \\
    python project-product-mcp-server/scripts/seed_demo_project.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE / "src") not in sys.path:
    sys.path.insert(0, str(_SERVICE / "src"))

from platform_project_product.schemas import (  # noqa: E402
    ExternalLink,
    ProductCreate,
    ProjectCreate,
    RepositoryBindingCreate,
)

BASE_URL = os.environ.get("PROJECT_PRODUCT_BASE_URL", "http://localhost:8000")
TOKEN = os.environ.get("PROJECT_PRODUCT_INTERNAL_TOKEN", "")
TENANT = os.environ.get("PROJECT_PRODUCT_TENANT_ID", "dataforall")
ACTOR = int(os.environ.get("PROJECT_PRODUCT_ACTOR_ID", "1"))

# ── Spec do seed (edite aqui) ────────────────────────────────────────────────
PRODUCT = {
    "slug": "devteam-demo",
    "name": "DevTeam Demo",
    "description": "Produto demo da jornada DevTeam (ADR-017).",
}
PROJECT = {
    "slug": "platform-devs",
    "name": "Platform DevTeam",
    "description": "Projeto demo com repos do ecossistema, ligados por external_link github.",
}
REPOS: list[dict[str, Any]] = [
    {
        "provider": "github",
        "connector_ref": "connector:github:dataforalltech",
        "repository_ref": "github:dataforalltech/platform-devs",
        "role": "source",
        "external_link": {
            "owner": "dataforalltech",
            "repo": "platform-devs",
            "url": "https://github.com/dataforalltech/platform-devs",
        },
    },
    {
        "provider": "github",
        "connector_ref": "connector:github:dataforalltech",
        "repository_ref": "github:dataforalltech/platform-connectors",
        "role": "source",
        "external_link": {
            "owner": "dataforalltech",
            "repo": "platform-connectors",
            "url": "https://github.com/dataforalltech/platform-connectors",
        },
    },
]


def _idempotency_key(suffix: str) -> str:
    # padrao aceito: ^[A-Za-z0-9._:-]+$ (min 8, max 128). Sanitiza '/' e afins.
    safe = re.sub(r"[^A-Za-z0-9._:-]", "-", suffix)
    return f"seed-{safe}"[:128]


def build_product_payload() -> dict[str, Any]:
    return ProductCreate(
        idempotency_key=_idempotency_key("product-devteam-demo"), **PRODUCT
    ).model_dump(mode="json")


def build_project_payload(product_id: str) -> dict[str, Any]:
    return ProjectCreate(
        idempotency_key=_idempotency_key("project-platform-devs"),
        product_id=product_id,
        **PROJECT,
    ).model_dump(mode="json")


def build_binding_payload(spec: dict[str, Any]) -> dict[str, Any]:
    return RepositoryBindingCreate(
        idempotency_key=_idempotency_key(f"binding-{spec['repository_ref']}"),
        provider=spec["provider"],
        connector_ref=spec["connector_ref"],
        repository_ref=spec["repository_ref"],
        role=spec["role"],
        external_link=ExternalLink(**spec["external_link"]),
    ).model_dump(mode="json")


def _headers() -> dict[str, str]:
    return {
        "X-Internal-Token": TOKEN,
        "X-Tenant-Id": TENANT,
        "X-Actor-Id": str(ACTOR),
        "Content-Type": "application/json",
    }


def seed() -> dict[str, Any]:
    import httpx

    with httpx.Client(base_url=BASE_URL, headers=_headers(), timeout=15.0) as client:
        pr = client.post("/api/internal/mcp/products", json=build_product_payload())
        pr.raise_for_status()
        product_id = pr.json()["product_id"]

        pj = client.post("/api/internal/mcp/projects", json=build_project_payload(product_id))
        pj.raise_for_status()
        project_id = pj.json()["project_id"]

        bindings: list[str] = []
        for spec in REPOS:
            rb = client.post(
                f"/api/internal/mcp/projects/{project_id}/repositories",
                json=build_binding_payload(spec),
            )
            rb.raise_for_status()
            bindings.append(rb.json()["binding_id"])

    return {"product_id": product_id, "project_id": project_id, "bindings": bindings}


def main() -> int:
    if not TOKEN:
        print(
            "Defina PROJECT_PRODUCT_INTERNAL_TOKEN (e opcional BASE_URL/TENANT_ID/ACTOR_ID).",
            file=sys.stderr,
        )
        return 2
    import json

    print(json.dumps(seed(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
