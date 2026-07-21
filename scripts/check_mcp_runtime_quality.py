#!/usr/bin/env python3
"""Local/pipeline gate for the manifest-driven MCP runtime surface."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audit_mcp_tools import audit_repository, runtime_gaps  # noqa: E402
from src.control_plane.artifact_generator import check_all  # noqa: E402
from src.control_plane.manifest_loader import load_catalog  # noqa: E402
from src.control_plane.manifest_validator import validate_catalog  # noqa: E402


def main() -> int:
    catalog = load_catalog(ROOT)
    errors = validate_catalog(catalog)
    errors.extend(check_all(catalog))
    if (ROOT / ".github" / "workflows").exists():
        errors.append("GitHub Actions is retired; .github/workflows must not exist")
    records = audit_repository(ROOT)
    errors.extend(runtime_gaps(records, ROOT))
    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}")
        return 1
    published = sum(1 for manifest in catalog.manifests.values() if manifest.gateway.enabled)
    print(
        f"OK: {len(catalog.manifests)} manifests, {len(catalog.contracts)} contracts, "
        f"{len(records)} implementations, {published} gateway providers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
