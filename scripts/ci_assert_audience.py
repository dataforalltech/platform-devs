#!/usr/bin/env python3
"""ci_assert_audience.py — trava a falha de integração nº 1 do MCP Gateway (401 audience mismatch).

STD-MCP-001 / STD-CICD-001: para cada persona MCP (`*-mcp-server/`), a audiência do inner
Twin Token DEVE ser consistente em três lugares, senão o gateway minta um inner token com
`aud` diferente do que o PEP do sidecar re-verifica → 401 em toda chamada.

Regra (derivação canônica do gateway, `app/registry/sources.py`):
    namespace          = name_microservice.removeprefix("platform-")
    audience esperada   = "mcp:" + namespace

Este guard confere, por server:
  1. settings.py            → NAMESPACE e o default de MCP_TWIN_AUDIENCE  == "mcp:<ns>"
  2. gateway/twin-gateway-services.entry.json → name/namespace/audience coerentes
  3. gateway/gateway-mapping.sql              → name_microservice = "platform-<ns>"

Uso:  python scripts/ci_assert_audience.py        # todos os *-mcp-server
      python scripts/ci_assert_audience.py backend-mcp-server ...
Sai 1 em qualquer divergência (ou registro ausente); imprime um relatório por server.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _servers(argv: list[str]) -> list[Path]:
    if argv:
        return [ROOT / a for a in argv]
    # Escopo: apenas servers que se REGISTRAM no gateway (têm gateway/). Os system-MCPs
    # ainda não-migrados (sem gateway/) ficam fora — não são personas mcp_http.
    return sorted(
        p for p in ROOT.glob("*-mcp-server")
        if (p / "gateway" / "twin-gateway-services.entry.json").exists()
    )


def _settings_facts(server: Path) -> tuple[str | None, str | None]:
    """Retorna (NAMESPACE, default de MCP_TWIN_AUDIENCE) lidos do settings.py (sem importar)."""
    text = (server / "src" / "config" / "settings.py").read_text(encoding="utf-8")
    ns = re.search(r'NAMESPACE\s*=\s*["\']([^"\']+)["\']', text)
    aud = re.search(r'mcp_twin_audience[^\n]*default\s*=\s*f?["\']([^"\']+)["\']', text)
    return (ns.group(1) if ns else None, aud.group(1) if aud else None)


def _entry_facts(server: Path) -> dict | None:
    f = server / "gateway" / "twin-gateway-services.entry.json"
    if not f.exists():
        return None
    arr = json.loads(f.read_text(encoding="utf-8"))
    return arr[0] if isinstance(arr, list) and arr else None


def _sql_name(server: Path) -> str | None:
    f = server / "gateway" / "gateway-mapping.sql"
    if not f.exists():
        return None
    m = re.search(r"name_microservice[^\n]*VALUES\s*\(\s*'([^']+)'", f.read_text(encoding="utf-8"), re.I | re.S)
    if m:
        return m.group(1)
    m = re.search(r"'(platform-[a-z0-9-]+)'", f.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def check(server: Path) -> list[str]:
    errs: list[str] = []
    ns, aud_default = _settings_facts(server)
    if not ns:
        return [f"{server.name}: NAMESPACE não encontrado em settings.py"]
    expected_aud = f"mcp:{ns}"
    expected_name = f"platform-{ns}"

    # o default costuma ser um f-string `f"mcp:{NAMESPACE}"` — resolve o placeholder.
    if aud_default:
        aud_default = aud_default.replace("{NAMESPACE}", ns)
        if aud_default != expected_aud:
            errs.append(f"{server.name}: settings MCP_TWIN_AUDIENCE default '{aud_default}' != '{expected_aud}'")

    entry = _entry_facts(server)
    if entry is None:
        errs.append(f"{server.name}: falta gateway/twin-gateway-services.entry.json (registro CI-3)")
    else:
        if entry.get("namespace") != ns:
            errs.append(f"{server.name}: entry.namespace '{entry.get('namespace')}' != '{ns}'")
        if entry.get("audience") != expected_aud:
            errs.append(f"{server.name}: entry.audience '{entry.get('audience')}' != '{expected_aud}'")
        if entry.get("name") != expected_name:
            errs.append(f"{server.name}: entry.name '{entry.get('name')}' != '{expected_name}'")

    sql_name = _sql_name(server)
    if sql_name is None:
        errs.append(f"{server.name}: falta/ilegível gateway/gateway-mapping.sql")
    elif sql_name != expected_name:
        errs.append(f"{server.name}: sql name_microservice '{sql_name}' != '{expected_name}'")

    if not errs:
        print(f"  ok  {server.name:32s} ns={ns} aud={expected_aud}")
    return errs


def main() -> int:
    servers = _servers(sys.argv[1:])
    if not servers:
        print("nenhum *-mcp-server com src/config/settings.py encontrado", file=sys.stderr)
        return 1
    print(f"== audience guard ({len(servers)} servers) ==")
    all_errs: list[str] = []
    for s in servers:
        all_errs += check(s)
    if all_errs:
        print("\nFALHAS:", file=sys.stderr)
        for e in all_errs:
            print("  ✗ " + e, file=sys.stderr)
        return 1
    print("== audiências consistentes ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
