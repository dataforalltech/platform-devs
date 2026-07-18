#!/usr/bin/env python3
"""Validate canonical MCP manifests and governed tool contracts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.control_plane.manifest_loader import CatalogError, load_catalog  # noqa: E402
from src.control_plane.manifest_validator import validate_catalog  # noqa: E402


def main() -> int:
    try:
        catalog = load_catalog(ROOT)
        errors = validate_catalog(catalog)
    except (CatalogError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {len(catalog.manifests)} manifests, {len(catalog.contracts)} tool contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
