"""Runtime provider registry generated from canonical manifests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class RegistryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    transport: dict[str, Any]
    security: dict[str, Any]
    tool_policies: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def tools_list_path(self) -> str:
        return self.transport["canonical_http"]["tools_list"]

    @property
    def tools_call_path(self) -> str:
        return self.transport["canonical_http"]["tools_call"]


class RuntimeRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(
            path
            or os.environ.get("MCP_REGISTRY_FILE", "/app/mcp-runtime-registry.json")
        )

    def _entries(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            entries = payload["services"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RegistryUnavailable(f"invalid runtime registry: {exc}") from exc
        if not isinstance(entries, dict):
            raise RegistryUnavailable("runtime registry services must be an object")
        return entries

    @staticmethod
    def _url(entry: dict[str, Any]) -> str | None:
        env_name = entry.get("url_env")
        if isinstance(env_name, str):
            value = os.environ.get(env_name)
            if value:
                return value.rstrip("/")
        if isinstance(entry.get("url"), str):
            return entry["url"].rstrip("/")
        return None

    def get(self, name: str) -> Provider | None:
        entry = self._entries().get(name)
        if not entry or not entry.get("gateway_enabled"):
            return None
        url = self._url(entry)
        if not url:
            raise RegistryUnavailable(f"provider {name} has no configured runtime URL")
        return Provider(
            name=name,
            url=url,
            transport=entry["transport"],
            security=entry["security"],
            tool_policies=entry.get("tool_policies", {}),
        )

    def list(self) -> list[Provider]:
        providers: list[Provider] = []
        for name, entry in sorted(self._entries().items()):
            if not entry.get("gateway_enabled"):
                continue
            url = self._url(entry)
            if not url:
                raise RegistryUnavailable(
                    f"gateway provider {name} has no configured runtime URL"
                )
            providers.append(
                Provider(
                    name=name,
                    url=url,
                    transport=entry["transport"],
                    security=entry["security"],
                    tool_policies=entry.get("tool_policies", {}),
                )
            )
        return providers


runtime_registry = RuntimeRegistry()
