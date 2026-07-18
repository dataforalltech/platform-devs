"""Read-only inventory and drift audit for MCP implementations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .manifest_loader import ManifestCatalog


@dataclass(frozen=True)
class InventoryReport:
    implementation_directories: list[str]
    covered_directories: list[str]
    uncovered_directories: list[str]
    root_mcp_scripts: list[str]
    dockerfiles: list[str]
    entrypoints: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _relative(root: Path, paths) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in paths)


def audit_inventory(catalog: ManifestCatalog) -> InventoryReport:
    root = catalog.root
    implementations = set(root.glob("*-mcp-server"))
    services = root / "services"
    if services.is_dir():
        implementations.update(services.glob("*-mcp-server"))
    covered: set[Path] = set()
    for manifest in catalog.manifests.values():
        paths = [manifest.ownership.source_path, *manifest.ownership.legacy_source_paths]
        for relative in filter(None, paths):
            candidate = (root / str(relative)).resolve()
            if candidate in {path.resolve() for path in implementations}:
                covered.add(candidate)
    resolved_implementations = {path.resolve() for path in implementations}
    return InventoryReport(
        implementation_directories=_relative(root, sorted(resolved_implementations)),
        covered_directories=_relative(root, sorted(covered)),
        uncovered_directories=_relative(root, sorted(resolved_implementations - covered)),
        root_mcp_scripts=_relative(root, root.glob("*-mcp.py")),
        dockerfiles=_relative(root, root.glob("**/Dockerfile*")),
        entrypoints=_relative(root, root.glob("**/*entrypoint*")),
    )
