#!/usr/bin/env python3
"""Read-only MCP discovery service backed by the generated manifest projection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException

REGISTRY_FILE = Path(os.environ.get("MCP_REGISTRY_FILE", "generated/mcp-runtime-registry.json"))


def _load_registry() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        services = payload["services"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid generated registry {REGISTRY_FILE}: {exc}") from exc
    if not isinstance(services, dict):
        raise RuntimeError(f"invalid generated registry {REGISTRY_FILE}: services must be an object")
    return services


def _runtime_url(entry: dict[str, Any]) -> str | None:
    if isinstance(entry.get("url"), str):
        return entry["url"].rstrip("/")
    env_name = entry.get("url_env")
    if isinstance(env_name, str):
        value = os.environ.get(env_name)
        return value.rstrip("/") if value else None
    return None


async def _discover(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    url = _runtime_url(entry)
    base = {
        "name": name,
        "status": "unconfigured" if not url else "offline",
        "classification": entry.get("classification", {}),
        "owner": entry.get("owner", {}),
        "transport": entry.get("transport", {}),
    }
    if not url:
        return base
    health_path = entry.get("transport", {}).get("canonical_http", {}).get(
        "health_ready", "/v1/health/ready"
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}{health_path}")
            response.raise_for_status()
            health = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {**base, "error": exc.__class__.__name__}
    return {**base, "status": "online", "health": health}


app = FastAPI(title="MCP Registry", version="2.0.0")


@app.get("/v1/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-registry"}


@app.get("/v1/health/ready")
async def health_ready() -> dict[str, str]:
    services = _load_registry()
    unconfigured = [
        name
        for name, entry in services.items()
        if entry.get("registry_enabled") and not _runtime_url(entry)
    ]
    if unconfigured:
        raise HTTPException(
            status_code=503,
            detail=f"registry providers are unconfigured: {', '.join(sorted(unconfigured))}",
        )
    return {"status": "ready", "service": "mcp-registry"}


@app.get("/services")
async def list_services() -> dict[str, Any]:
    services = _load_registry()
    discovered = [
        await _discover(name, entry)
        for name, entry in sorted(services.items())
        if entry.get("registry_enabled")
    ]
    return {
        "total": len(discovered),
        "online": sum(item["status"] == "online" for item in discovered),
        "offline": sum(item["status"] == "offline" for item in discovered),
        "unconfigured": sum(item["status"] == "unconfigured" for item in discovered),
        "services": discovered,
    }


@app.get("/services/{name}")
async def get_service(name: str) -> dict[str, Any]:
    entry = _load_registry().get(name)
    if entry is None or not entry.get("registry_enabled"):
        raise HTTPException(status_code=404, detail="MCP provider not found")
    return await _discover(name, entry)


def main() -> None:
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
