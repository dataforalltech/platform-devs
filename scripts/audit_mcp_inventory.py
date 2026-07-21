#!/usr/bin/env python3
"""Report implementation inventory and fail on unmanifested MCP directories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.control_plane.inventory import audit_inventory  # noqa: E402
from src.control_plane.manifest_loader import load_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit_inventory(load_catalog(ROOT))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"implementations={len(report.implementation_directories)}")
        print(f"covered={len(report.covered_directories)}")
        print(f"uncovered={len(report.uncovered_directories)}")
        for path in report.uncovered_directories:
            print(f"UNMANIFESTED: {path}")
    return 1 if report.uncovered_directories else 0


if __name__ == "__main__":
    raise SystemExit(main())
