"""Load the canonical manifest and governed tool-contract catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .manifest_models import MCPManifest, ToolContract


class CatalogError(ValueError):
    """Raised when the canonical catalog is ambiguous or invalid."""


@dataclass(frozen=True)
class ManifestCatalog:
    root: Path
    manifests: dict[str, MCPManifest]
    contracts: dict[tuple[str, str], ToolContract]
    sources: dict[str, Path]
    contract_sources: dict[tuple[str, str], Path]

    def executable(self, *, include_experimental: bool = False) -> list[MCPManifest]:
        statuses = {"active", "experimental"} if include_experimental else {"active"}
        return sorted(
            (manifest for manifest in self.manifests.values() if manifest.status in statuses),
            key=lambda manifest: manifest.id,
        )


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatalogError(f"{path}: expected one YAML object")
    return payload


def load_catalog(root: str | Path) -> ManifestCatalog:
    root_path = Path(root).resolve()
    manifests: dict[str, MCPManifest] = {}
    sources: dict[str, Path] = {}
    for folder in (root_path / "manifests" / "mcps", root_path / "manifests" / "planned"):
        if not folder.is_dir():
            raise CatalogError(f"missing canonical manifest directory: {folder}")
        for path in sorted(folder.glob("*.yaml")):
            manifest = MCPManifest.model_validate(_read_yaml(path))
            if manifest.id in manifests:
                raise CatalogError(f"duplicate manifest id {manifest.id}: {sources[manifest.id]} and {path}")
            if folder.name == "planned" and manifest.status != "planned":
                raise CatalogError(f"{path}: only planned manifests belong in manifests/planned")
            if folder.name == "mcps" and manifest.status == "planned":
                raise CatalogError(f"{path}: planned manifests belong in manifests/planned")
            manifests[manifest.id] = manifest
            sources[manifest.id] = path

    contracts: dict[tuple[str, str], ToolContract] = {}
    contract_sources: dict[tuple[str, str], Path] = {}
    contract_dir = root_path / "contracts" / "tools"
    if contract_dir.is_dir():
        for path in sorted(contract_dir.glob("*.yaml")):
            contract = ToolContract.model_validate(_read_yaml(path))
            key = (contract.provider_id, contract.name)
            if key in contracts:
                raise CatalogError(f"duplicate tool contract {contract.provider_id}.{contract.name}")
            contracts[key] = contract
            contract_sources[key] = path
    return ManifestCatalog(
        root=root_path,
        manifests=manifests,
        contracts=contracts,
        sources=sources,
        contract_sources=contract_sources,
    )
