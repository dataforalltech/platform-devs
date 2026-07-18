"""Manifest-driven MCP control plane.

The capability/tool domain model remains owned by :mod:`platform_catalog`.  This
package owns the operational projection: which providers exist, where their
implementation lives, and which ones are eligible for each runtime surface.
"""

from .manifest_loader import ManifestCatalog, load_catalog
from .manifest_models import MCPManifest, ToolContract

__all__ = ["MCPManifest", "ManifestCatalog", "ToolContract", "load_catalog"]
