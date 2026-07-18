#!/usr/bin/env python3
"""Generate or verify all manifest-derived artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.control_plane.artifact_generator import check_all, write_all  # noqa: E402
from src.control_plane.manifest_loader import load_catalog  # noqa: E402
from src.control_plane.manifest_validator import validate_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated artifacts drift")
    args = parser.parse_args()
    catalog = load_catalog(ROOT)
    errors = validate_catalog(catalog)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if args.check:
        drift = check_all(catalog)
        for item in drift:
            print(f"ERROR: {item}")
        if drift:
            return 1
        print("OK: generated artifacts match canonical manifests")
        return 0
    changed = write_all(catalog)
    for path in changed:
        print(f"WROTE: {path}")
    if not changed:
        print("OK: no generated artifacts changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
