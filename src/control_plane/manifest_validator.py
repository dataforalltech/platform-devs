"""Cross-manifest validation that needs repository and catalog context."""

from __future__ import annotations

import os
from pathlib import Path

from .manifest_loader import ManifestCatalog


def validate_catalog(catalog: ManifestCatalog) -> list[str]:
    errors: list[str] = []
    known = set(catalog.manifests)
    ports: dict[int, str] = {}
    referenced_contracts: set[Path] = set()

    for manifest in catalog.manifests.values():
        source = catalog.sources[manifest.id]
        if manifest.ownership.source_repo == "dataforalltech/platform-devs":
            paths = [manifest.ownership.source_path, *manifest.ownership.legacy_source_paths]
            for relative in filter(None, paths):
                if not (catalog.root / str(relative)).exists():
                    errors.append(f"{source}: local source path does not exist: {relative}")
        if manifest.runtime.mode == "local" and manifest.runtime.cwd:
            if not (catalog.root / manifest.runtime.cwd).is_dir():
                errors.append(f"{source}: runtime cwd does not exist: {manifest.runtime.cwd}")
        if manifest.runtime.dockerfile:
            dockerfile = (
                catalog.root
                / (manifest.runtime.build_context or ".")
                / manifest.runtime.dockerfile
            ).resolve()
            if not dockerfile.is_file():
                errors.append(
                    f"{source}: dockerfile does not exist relative to build_context: "
                    f"{manifest.runtime.dockerfile}"
                )
        if manifest.network.host_port and manifest.status in {"active", "experimental"}:
            previous = ports.setdefault(manifest.network.host_port, manifest.id)
            if previous != manifest.id:
                errors.append(
                    f"host port {manifest.network.host_port} collides: {previous} and {manifest.id}"
                )
        for dependency in manifest.dependencies:
            if dependency not in known:
                errors.append(f"{source}: unknown dependency: {dependency}")
            elif manifest.status in {"active", "experimental"} and catalog.manifests[
                dependency
            ].status not in {"active", "experimental"}:
                errors.append(
                    f"{source}: executable provider depends on non-executable provider: {dependency}"
                )
        if manifest.tool_catalog and not (catalog.root / manifest.tool_catalog).exists():
            errors.append(f"{source}: tool_catalog does not exist: {manifest.tool_catalog}")
        for contract_path in manifest.tool_contracts:
            resolved = (catalog.root / contract_path).resolve()
            referenced_contracts.add(resolved)
            if not resolved.is_file():
                errors.append(f"{source}: tool contract does not exist: {contract_path}")

    for provider_id, name in catalog.contracts:
        if provider_id not in known:
            errors.append(f"tool contract references unknown provider: {provider_id}.{name}")
            continue
        source = catalog.contract_sources[(provider_id, name)].resolve()
        provider_contracts = {
            (catalog.root / path).resolve()
            for path in catalog.manifests[provider_id].tool_contracts
        }
        if source not in provider_contracts:
            errors.append(
                f"tool contract is not referenced by its provider manifest: {provider_id}.{name}"
            )
    actual_contracts = {path.resolve() for path in (catalog.root / "contracts" / "tools").glob("*.yaml")}
    for path in sorted(actual_contracts - referenced_contracts):
        errors.append(f"unreferenced tool contract: {path.relative_to(catalog.root)}")
    return sorted(errors)


def resolve_runtime_url(manifest, *, environ: dict[str, str] | None = None) -> str | None:
    env = environ if environ is not None else os.environ
    if manifest.runtime.mode == "local":
        if not (manifest.runtime.service_name and manifest.network.internal_port):
            return None
        return f"http://{manifest.runtime.service_name}:{manifest.network.internal_port}"
    if manifest.runtime.mode == "external" and manifest.runtime.base_url_env:
        return env.get(manifest.runtime.base_url_env)
    return None
